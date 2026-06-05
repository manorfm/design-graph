"""
Writes extracted entities to the Kuzu graph database.

Design rules:
- GraphWriter is always constructed with an open write connection.
- All writes are sequential (Kuzu does not support concurrent writes).
- Idempotency: duplicate inserts are silently ignored via _safe_execute.
- CONTAINS relationships are only created when both parent and child nodes exist.
"""

from __future__ import annotations

import json
import logging
import sys

import kuzu

from design_graph.core.models import (
    DesignToken,
    ExtractedComponent,
    ExtractedScreen,
    ExtractedSection,
)
from design_graph.graph.schema import STATS_QUERIES

logger = logging.getLogger(__name__)


class GraphWriter:
    """Sequential writer for the design graph. One instance per build."""

    def __init__(self, conn: kuzu.Connection) -> None:
        self._conn = conn
        self._inserted_comp_names: set[str] = set()
        self._inserted_style_ids:  set[str] = set()
        self._inserted_inter_ids:  set[str] = set()
        self._inserted_text_ids:   set[str] = set()
        self._token_rel_keys:      set[str] = set()
        self._contains_keys:       set[str] = set()

    @property
    def inserted_names(self) -> frozenset[str]:
        """Names of components already written — read-only snapshot."""
        return frozenset(self._inserted_comp_names)

    # ── Public write API ──────────────────────────────────────────────────────

    def write_tokens(self, tokens: list[DesignToken]) -> int:
        """Insert Token nodes. Returns the number of tokens successfully inserted."""
        inserted = 0
        for token in tokens:
            ok = self._safe_execute(
                "CREATE (:Token {id:$id, category:$cat, label:$lbl, value:$val, usage:$use})",
                {"id": token.id, "cat": token.category, "lbl": token.label,
                 "val": token.value, "use": token.usage},
            )
            if ok:
                inserted += 1
        logger.debug("writer: wrote %d tokens", inserted)
        return inserted

    def write_component(
        self,
        comp: ExtractedComponent,
        token_map: dict[str, list[DesignToken]],
    ) -> None:
        """
        Insert Component node with its Style, Interaction, UIText sub-nodes
        and the CONTAINS relationships to child components.
        """
        if comp.name in self._inserted_comp_names:
            logger.debug("writer: skipping duplicate component %s", comp.name)
            return

        self._safe_execute(
            "CREATE (:Component {name:$n, comp_type:$t, jsx_snippet:$s, occurrence:$o, classes:$c})",
            {"n": comp.name, "t": comp.comp_type, "s": comp.jsx_snippet,
             "o": comp.occurrence, "c": comp.classes},
        )
        self._inserted_comp_names.add(comp.name)

        # Styles
        for style in comp.styles:
            if style.id in self._inserted_style_ids:
                continue
            self._inserted_style_ids.add(style.id)
            self._safe_execute(
                "CREATE (:Style {id:$id, element:$el, state:$st, property:$pr, value:$vl})",
                {"id": style.id, "el": style.element, "st": style.state,
                 "pr": style.property, "vl": style.value},
            )
            self._safe_execute(
                "MATCH (c:Component {name:$cn}),(s:Style {id:$sid}) CREATE (c)-[:HAS_STYLE]->(s)",
                {"cn": comp.name, "sid": style.id},
            )
            # Link style value to a design token if one matches
            for token in token_map.get(style.value.lower(), []):
                rel_key = f"{comp.name}_{token.id}"
                if rel_key not in self._token_rel_keys:
                    self._token_rel_keys.add(rel_key)
                    self._safe_execute(
                        "MATCH (c:Component {name:$cn}),(t:Token {id:$tid}) "
                        "CREATE (c)-[:USES_TOKEN]->(t)",
                        {"cn": comp.name, "tid": token.id},
                    )

        # Interactions
        for inter in comp.interactions:
            if inter.id in self._inserted_inter_ids:
                continue
            self._inserted_inter_ids.add(inter.id)
            self._safe_execute(
                "CREATE (:Interaction {id:$id, trigger:$tr, css_prop:$pr, "
                "from_val:$fv, to_val:$tv, transition:$tn})",
                {"id": inter.id, "tr": inter.trigger, "pr": inter.css_prop,
                 "fv": inter.from_val, "tv": inter.to_val, "tn": inter.transition},
            )
            self._safe_execute(
                "MATCH (c:Component {name:$cn}),(i:Interaction {id:$iid}) "
                "CREATE (c)-[:HAS_INTERACTION]->(i)",
                {"cn": comp.name, "iid": inter.id},
            )

        # UITexts
        for text in comp.texts:
            if text.id in self._inserted_text_ids:
                continue
            self._inserted_text_ids.add(text.id)
            self._safe_execute(
                "CREATE (:UIText {id:$id, content:$ct, text_type:$ty, source:$src, element:$el})",
                {"id": text.id, "ct": text.content, "ty": text.text_type,
                 "src": text.source, "el": text.element},
            )
            self._safe_execute(
                "MATCH (c:Component {name:$cn}),(t:UIText {id:$tid}) "
                "CREATE (c)-[:COMP_HAS_TEXT]->(t)",
                {"cn": comp.name, "tid": text.id},
            )

        # CONTAINS relationships (only when child already exists in graph)
        for child_name in comp.child_refs:
            if child_name not in self._inserted_comp_names:
                continue
            contains_key = f"{comp.name}→{child_name}"
            if contains_key in self._contains_keys:
                continue
            self._contains_keys.add(contains_key)
            self._safe_execute(
                "MATCH (p:Component {name:$p}),(c:Component {name:$c}) "
                "CREATE (p)-[:CONTAINS {weight:1}]->(c)",
                {"p": comp.name, "c": child_name},
            )

    def write_screen(
        self,
        screen: ExtractedScreen,
        sections: list[ExtractedSection],
        token_map: dict[str, list[DesignToken]],
    ) -> None:
        """
        Insert Screen node, USES_COMPONENT edges, Section nodes, and SECTION_USES edges.
        Creates "shell" Component nodes for references that were never extracted as functions.
        """
        self._safe_execute(
            "CREATE (:Screen {name:$n, component_count:$cc, sections_count:$sc})",
            {"n": screen.name, "cc": len(screen.component_refs), "sc": len(sections)},
        )

        for comp_name in screen.component_refs:
            self._ensure_component_exists(comp_name)
            rel_key = f"{screen.name}→{comp_name}"
            self._safe_execute(
                "MATCH (s:Screen {name:$sn}),(c:Component {name:$cn}) "
                "CREATE (s)-[:USES_COMPONENT]->(c)",
                {"sn": screen.name, "cn": comp_name},
            )

        for section in sections:
            self._safe_execute(
                "CREATE (:Section {id:$id, screen:$sc, name:$nm, "
                "styles_json:$sj, components_json:$cj, texts_json:$tj, "
                "jsx_snippet:$jsx, detection_method:$dm})",
                {
                    "id": section.id, "sc": section.screen, "nm": section.name,
                    "sj": json.dumps(section.styles),
                    "cj": json.dumps(section.component_refs),
                    "tj": json.dumps(section.texts),
                    "jsx": section.jsx_snippet,
                    "dm": section.detection_method,
                },
            )
            self._safe_execute(
                "MATCH (s:Screen {name:$sn}),(sec:Section {id:$sid}) "
                "CREATE (s)-[:HAS_SECTION]->(sec)",
                {"sn": screen.name, "sid": section.id},
            )
            for comp_name in section.component_refs:
                self._ensure_component_exists(comp_name)
                self._safe_execute(
                    "MATCH (sec:Section {id:$sid}),(c:Component {name:$cn}) "
                    "CREATE (sec)-[:SECTION_USES]->(c)",
                    {"sid": section.id, "cn": comp_name},
                )

        logger.debug("writer: wrote screen %s with %d sections", screen.name, len(sections))

    def get_stats(self) -> dict[str, int]:
        """Execute STATS_QUERIES and return node/rel counts."""
        stats: dict[str, int] = {}
        for name, cypher in STATS_QUERIES.items():
            try:
                result = self._conn.execute(cypher)
                stats[name] = result.get_next()[0] if result.has_next() else 0
            except Exception as exc:  # noqa: BLE001
                logger.warning("writer: stats query failed for %s: %s", name, exc)
                stats[name] = -1
        return stats

    # ── Private helpers ───────────────────────────────────────────────────────

    def _ensure_component_exists(self, name: str) -> None:
        """Create a minimal 'shell' component if it hasn't been inserted yet."""
        if name not in self._inserted_comp_names:
            self._safe_execute(
                "CREATE (:Component {name:$n, comp_type:$t, jsx_snippet:'', "
                "occurrence:1, classes:''})",
                {"n": name, "t": "component"},
            )
            self._inserted_comp_names.add(name)

    def _safe_execute(self, cypher: str, params: dict | None = None) -> bool:
        """Execute a Cypher statement. Returns False on error (never raises)."""
        try:
            self._conn.execute(cypher, params or {})
            return True
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[writer] SKIP ({type(exc).__name__}): {exc!r}\n")
            return False
