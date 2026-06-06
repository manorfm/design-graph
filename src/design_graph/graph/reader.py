"""
Read-only query layer for the design graph.

GraphReader provides typed access to graph data for the MCP server and CLI.
It never executes CREATE, DELETE, or MERGE — only MATCH queries.

Fuzzy name resolution is built in: get_screen("Restaurants") resolves to
"RestaurantsPage" using prefix → suffix → contains matching.
"""

from __future__ import annotations

import json
import logging

import kuzu

logger = logging.getLogger(__name__)


class GraphReader:
    """Read-only interface to a Kuzu design-graph database."""

    def __init__(self, conn: kuzu.Connection) -> None:
        self._conn = conn

    # ── Screens ───────────────────────────────────────────────────────────────

    def list_screens(self) -> list[dict]:
        rows = self._q(
            "MATCH (s:Screen) RETURN s.name, s.component_count, s.sections_count "
            "ORDER BY s.component_count DESC"
        )
        screens = []
        for row in rows:
            components = self._q(
                "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(c:Component) "
                "RETURN c.name ORDER BY c.name LIMIT 5",
                {"n": row["s.name"]},
            )
            screens.append({
                "name":            row["s.name"],
                "component_count": row["s.component_count"],
                "sections_count":  row["s.sections_count"],
                "top_components":  [c["c.name"] for c in components],
            })
        return screens

    def get_screen(self, name: str) -> dict | None:
        resolved = self._fuzzy_find_screen(name)
        if not resolved:
            return None

        screen_row = self._q(
            "MATCH (s:Screen {name:$n}) "
            "RETURN s.name, s.component_count, s.sections_count",
            {"n": resolved},
        )
        if not screen_row:
            return None
        s = screen_row[0]

        components = self._q(
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(c:Component) "
            "RETURN c.name, c.comp_type ORDER BY c.comp_type, c.name",
            {"n": resolved},
        )
        sections = self._q(
            "MATCH (s:Screen {name:$n})-[:HAS_SECTION]->(sec:Section) "
            "RETURN sec.name, sec.components_json, sec.texts_json, "
            "       sec.styles_json, sec.detection_method",
            {"n": resolved},
        )
        texts = self._q(
            "MATCH (s:Screen {name:$n})-[:SCREEN_HAS_TEXT]->(t:UIText) "
            "RETURN t.content, t.text_type, t.element ORDER BY t.text_type",
            {"n": resolved},
        )

        return {
            "name":            s["s.name"],
            "component_count": s["s.component_count"],
            "sections_count":  s["s.sections_count"],
            "components":      components,
            "sections":        sections,
            "texts":           texts[:20],
        }

    # ── Components ────────────────────────────────────────────────────────────

    def get_component(self, name: str) -> dict | None:
        resolved = self._fuzzy_find_component(name)
        if not resolved:
            return None

        rows = self._q(
            "MATCH (c:Component {name:$n}) "
            "RETURN c.name, c.comp_type, c.jsx_snippet, c.occurrence, c.classes",
            {"n": resolved},
        )
        if not rows:
            return None
        comp = rows[0]

        styles       = self._q(
            "MATCH (c:Component {name:$n})-[:HAS_STYLE]->(s:Style) "
            "RETURN s.state, s.property, s.value ORDER BY s.state, s.property",
            {"n": resolved},
        )
        tokens       = self._q(
            "MATCH (c:Component {name:$n})-[:USES_TOKEN]->(t:Token) "
            "RETURN t.label, t.value, t.category ORDER BY t.category",
            {"n": resolved},
        )
        texts        = self._q(
            "MATCH (c:Component {name:$n})-[:COMP_HAS_TEXT]->(t:UIText) "
            "RETURN t.content, t.text_type, t.element ORDER BY t.text_type",
            {"n": resolved},
        )
        interactions = self._q(
            "MATCH (c:Component {name:$n})-[:HAS_INTERACTION]->(i:Interaction) "
            "RETURN i.trigger, i.css_prop, i.from_val, i.to_val, i.transition",
            {"n": resolved},
        )
        screens_using = self._q(
            "MATCH (s:Screen)-[:USES_COMPONENT]->(c:Component {name:$n}) RETURN s.name",
            {"n": resolved},
        )
        children = self.get_component_children(resolved)

        return {
            **comp,
            "styles":        styles,
            "tokens":        tokens,
            "texts":         texts[:15],
            "interactions":  interactions,
            "screens_using": [r["s.name"] for r in screens_using],
            "children":      children,
        }

    def get_component_children(self, name: str) -> list[str]:
        """Return names of components directly contained by this component (via CONTAINS)."""
        rows = self._q(
            "MATCH (p:Component {name:$n})-[:CONTAINS]->(c:Component) "
            "RETURN c.name ORDER BY c.name",
            {"n": name},
        )
        return [r["c.name"] for r in rows]

    def get_component_parents(self, name: str) -> list[str]:
        """Return names of components that contain this component (via CONTAINS)."""
        rows = self._q(
            "MATCH (p:Component)-[:CONTAINS]->(c:Component {name:$n}) "
            "RETURN p.name ORDER BY p.name",
            {"n": name},
        )
        return [r["p.name"] for r in rows]

    def find_screens_using_comp_transitively(self, comp_name: str) -> list[str]:
        """
        Return screen names that use comp_name at any nesting depth (up to 3 levels).
        Uses the CONTAINS relationship chain to traverse composition.
        """
        rows = self._q(
            "MATCH (s:Screen)-[:USES_COMPONENT*1..3]->(c:Component {name:$n}) "
            "RETURN DISTINCT s.name ORDER BY s.name",
            {"n": comp_name},
        )
        return [r["s.name"] for r in rows]

    # ── Sections ──────────────────────────────────────────────────────────────

    def get_section(self, screen: str, section_hint: str) -> dict | None:
        rows = self._q(
            "MATCH (s:Screen {name:$sn})-[:HAS_SECTION]->(sec:Section) "
            "WHERE toLower(sec.name) CONTAINS toLower($sec) "
            "RETURN sec.id, sec.name, sec.styles_json, sec.components_json, "
            "       sec.texts_json, sec.jsx_snippet, sec.detection_method",
            {"sn": screen, "sec": section_hint},
        )
        if not rows:
            return None
        sec = rows[0]
        return {
            "id":               sec["sec.id"],
            "name":             sec["sec.name"],
            "detection_method": sec["sec.detection_method"],
            "styles":           json.loads(sec["sec.styles_json"] or "{}"),
            "component_refs":   json.loads(sec["sec.components_json"] or "[]"),
            "texts":            json.loads(sec["sec.texts_json"] or "[]"),
            "jsx_snippet":      sec["sec.jsx_snippet"],
        }

    # ── Tokens ────────────────────────────────────────────────────────────────

    def get_tokens(self, category: str | None = None) -> list[dict]:
        if category:
            return self._q(
                "MATCH (t:Token {category:$cat}) "
                "RETURN t.category, t.label, t.value, t.usage "
                "ORDER BY t.usage DESC",
                {"cat": category},
            )
        return self._q(
            "MATCH (t:Token) "
            "RETURN t.category, t.label, t.value, t.usage "
            "ORDER BY t.category, t.usage DESC"
        )

    def find_token_usage(self, value: str) -> list[dict]:
        tokens = self._q(
            "MATCH (t:Token) WHERE toLower(t.value) CONTAINS toLower($val) "
            "OR toLower(t.label) CONTAINS toLower($val) "
            "RETURN t.id, t.label, t.value, t.category",
            {"val": value},
        )
        result = []
        for tok in tokens:
            comps = self._q(
                "MATCH (c:Component)-[:USES_TOKEN]->(t:Token {id:$tid}) "
                "RETURN c.name, c.comp_type",
                {"tid": tok["t.id"]},
            )
            screens = self._q(
                "MATCH (s:Screen)-[:USES_COMPONENT]->(c:Component)-[:USES_TOKEN]->"
                "(t:Token {id:$tid}) RETURN DISTINCT s.name",
                {"tid": tok["t.id"]},
            )
            result.append({**tok, "components": comps, "screens": [r["s.name"] for r in screens]})
        return result

    # ── Interactions ──────────────────────────────────────────────────────────

    def get_interactions(self, comp_name: str) -> list[dict]:
        resolved = self._fuzzy_find_component(comp_name)
        if not resolved:
            return []
        return self._q(
            "MATCH (c:Component {name:$n})-[:HAS_INTERACTION]->(i:Interaction) "
            "RETURN i.trigger, i.css_prop, i.from_val, i.to_val, i.transition",
            {"n": resolved},
        )

    # ── Full JSX ──────────────────────────────────────────────────────────────

    def get_full_jsx(self, name: str) -> str:
        comp_rows = self._q(
            "MATCH (c:Component {name:$n}) RETURN c.jsx_snippet, c.comp_type",
            {"n": name},
        )
        if comp_rows and comp_rows[0].get("c.jsx_snippet"):
            return comp_rows[0]["c.jsx_snippet"]
        return ""

    # ── Impact analysis ───────────────────────────────────────────────────────

    def get_impact(self, name: str) -> dict:
        comp_rows = self._q(
            "MATCH (c:Component {name:$n}) RETURN c.name, c.comp_type", {"n": name}
        )
        if comp_rows:
            screens = self.find_screens_using_comp_transitively(name)
            sections = self._q(
                "MATCH (sec:Section)-[:SECTION_USES]->(c:Component {name:$n}) "
                "RETURN sec.screen, sec.name",
                {"n": name},
            )
            tokens_used = self._q(
                "MATCH (c:Component {name:$n})-[:USES_TOKEN]->(t:Token) "
                "RETURN t.label, t.value",
                {"n": name},
            )
            return {
                "found":        True,
                "type":         comp_rows[0]["c.comp_type"],
                "screens":      screens,
                "sections":     sections,
                "tokens_used":  tokens_used,
            }

        tok_rows = self._q(
            "MATCH (t:Token) WHERE t.label=$n OR t.value=$n "
            "RETURN t.id, t.label, t.value",
            {"n": name},
        )
        if tok_rows:
            tok = tok_rows[0]
            comps = self._q(
                "MATCH (c:Component)-[:USES_TOKEN]->(t:Token {id:$tid}) RETURN c.name",
                {"tid": tok["t.id"]},
            )
            screens = self._q(
                "MATCH (s:Screen)-[:USES_COMPONENT]->(c:Component)-[:USES_TOKEN]->"
                "(t:Token {id:$tid}) RETURN DISTINCT s.name",
                {"tid": tok["t.id"]},
            )
            return {
                "found":      True,
                "label":      tok["t.label"],
                "value":      tok["t.value"],
                "components": [c["c.name"] for c in comps],
                "screens":    [s["s.name"] for s in screens],
            }

        return {"found": False}

    # ── Stats ──────────────────────────────────────────────────────────────────

    def count_nodes(self) -> dict[str, int]:
        from design_graph.graph.schema import STATS_QUERIES
        result: dict[str, int] = {}
        for key, cypher in STATS_QUERIES.items():
            rows = self._q(cypher)
            result[key] = rows[0][list(rows[0].keys())[0]] if rows else 0
        return result

    # ── Fuzzy name resolution ─────────────────────────────────────────────────

    def _fuzzy_find_screen(self, hint: str) -> str | None:
        all_screens = self._q("MATCH (s:Screen) RETURN s.name")
        names = [r["s.name"] for r in all_screens]
        return _fuzzy_match(hint, names)

    def _fuzzy_find_component(self, hint: str) -> str | None:
        all_comps = self._q("MATCH (c:Component) RETURN c.name")
        names = [r["c.name"] for r in all_comps]
        return _fuzzy_match(hint, names)

    # ── Query helper ──────────────────────────────────────────────────────────

    def _q(self, cypher: str, params: dict | None = None) -> list[dict]:
        """Execute a read-only Cypher query and return rows as dicts."""
        try:
            result = self._conn.execute(cypher, params or {})
            cols = result.get_column_names()
            rows = []
            while result.has_next():
                rows.append(dict(zip(cols, result.get_next())))
            return rows
        except Exception as exc:  # noqa: BLE001
            logger.warning("reader: query failed: %s\n%s", cypher[:80], exc)
            return []


def _fuzzy_match(hint: str, names: list[str]) -> str | None:
    """
    Resolve a partial name to a full name using priority matching:
    1. Exact (case-insensitive)
    2. Prefix
    3. Suffix
    4. Contains
    Returns None if no match or hint is empty.
    """
    lower = hint.lower().strip()
    if not lower:
        return None
    for name in names:
        if name.lower() == lower:
            return name
    prefix  = [n for n in names if n.lower().startswith(lower)]
    if prefix:
        return prefix[0]
    suffix  = [n for n in names if n.lower().endswith(lower)]
    if suffix:
        return suffix[0]
    contains = [n for n in names if lower in n.lower()]
    if contains:
        return contains[0]
    return None
