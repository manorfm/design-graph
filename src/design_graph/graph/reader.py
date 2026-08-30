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
from collections import defaultdict
from pathlib import Path

import kuzu

from design_graph.core.constants import (
    DECORATIVE_DIMENSION_MAX_PX,
    LAYOUT_CSS_PROPERTIES,
    _LAYOUT_FAST_PATH_PROPERTIES,
)
from design_graph.core.models import resolve_icon_markers
from design_graph.core.patterns import RE_ICON_MARKER

logger = logging.getLogger(__name__)


class GraphReader:
    """Read-only interface to a Kuzu design-graph database."""

    def __init__(self, conn: kuzu.Connection, state_path: Path | None = None) -> None:
        self._conn = conn
        # Optional: <database>.state.json for this same document, set by
        # callers that know the db's filesystem path (the MCP server, which
        # discovers readers by globbing *.db). Lets get_build_diff() answer
        # "what changed since the last build" by reading the diff already
        # persisted there, without comparing two Kuzu databases from scratch.
        self._state_path = state_path

    # ── Screens ───────────────────────────────────────────────────────────────

    def list_screens(self) -> list[dict]:
        """
        Return all screens sorted by component count.

        Uses 2 queries instead of N+1: one for screen metadata and one JOIN
        query for all screen-component relationships. Grouping is done in Python.
        """
        screen_rows = self._q(
            "MATCH (s:Screen) RETURN s.name, s.component_count, s.sections_count "
            "ORDER BY s.component_count DESC"
        )
        if not screen_rows:
            return []

        # Single JOIN query for all top-component names across all screens
        comp_rows = self._q(
            "MATCH (s:Screen)-[:USES_COMPONENT]->(c:Component) "
            "RETURN s.name AS screen_name, c.name AS comp_name "
            "ORDER BY screen_name, comp_name"
        )

        top_by_screen: dict[str, list[str]] = defaultdict(list)
        for row in comp_rows:
            bucket = top_by_screen[row["screen_name"]]
            if len(bucket) < 5:
                bucket.append(row["comp_name"])

        return [
            {
                "name":            r["s.name"],
                "component_count": r["s.component_count"],
                "sections_count":  r["s.sections_count"],
                "top_components":  top_by_screen[r["s.name"]],
            }
            for r in screen_rows
        ]

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
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(c:Component)"
            "-[:COMP_HAS_TEXT]->(t:UIText) "
            "RETURN DISTINCT t.content, t.text_type, t.element "
            "ORDER BY t.text_type",
            {"n": resolved},
        )
        return {
            "name":            s["s.name"],
            "component_count": s["s.component_count"],
            "sections_count":  s["s.sections_count"],
            "components":      components,
            "sections":        sections,
            "texts":           texts,
        }

    # ── Components ────────────────────────────────────────────────────────────

    def get_component(self, name: str) -> dict | None:
        resolved = self._fuzzy_find_component(name)
        if not resolved:
            return None

        rows = self._q(
            "MATCH (c:Component {name:$n}) "
            "RETURN c.name, c.comp_type, c.jsx_snippet, c.occurrence, c.classes, c.truncated_fields",
            {"n": resolved},
        )
        if not rows:
            return None
        comp = rows[0]
        comp["c.jsx_snippet"] = self._resolve_icons(comp["c.jsx_snippet"])

        styles       = self._q(
            # media != '' rows are @media-scoped variants (C35) — this tool
            # doesn't distinguish them from the unconditional default, so it
            # excludes them rather than silently presenting one as the other
            # (get_component_spec is the one place that surfaces them, labeled).
            "MATCH (c:Component {name:$n})-[:HAS_STYLE]->(s:Style) "
            "WHERE s.media = '' "
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
        children = self.get_component_children(resolved)

        return {
            **comp,
            "styles":        styles,
            "tokens":        tokens,
            "texts":         texts[:15],
            "interactions":  interactions,
            "screens_using": self.find_screens_using_comp_transitively(resolved),
            "children":      children,
        }

    def list_components(self, comp_type: str | None = None) -> list[dict]:
        """
        Return all components sorted by occurrence descending.
        If comp_type is provided, return only components of that semantic type.
        """
        if comp_type:
            rows = self._q(
                "MATCH (c:Component {comp_type:$t}) "
                "RETURN c.name, c.comp_type, c.occurrence "
                "ORDER BY c.occurrence DESC",
                {"t": comp_type},
            )
        else:
            rows = self._q(
                "MATCH (c:Component) "
                "RETURN c.name, c.comp_type, c.occurrence "
                "ORDER BY c.occurrence DESC"
            )
        logger.debug("reader: list_components(comp_type=%s) → %d results", comp_type, len(rows))
        return rows

    def get_component_spec(self, name: str) -> dict | None:
        """
        Return structured component spec for AI agent consumption.
        Aggregates metadata, styles grouped by state, tokens, texts,
        interactions, parent/child hierarchy, and screens using this component.
        Uses fuzzy name resolution. Returns None if not found.
        """
        resolved = self._fuzzy_find_component(name)
        if not resolved:
            return None

        rows = self._q(
            "MATCH (c:Component {name:$n}) "
            "RETURN c.name, c.comp_type, c.jsx_snippet, c.occurrence, c.classes, c.truncated_fields",
            {"n": resolved},
        )
        if not rows:
            return None
        comp = rows[0]
        comp["c.jsx_snippet"] = self._resolve_icons(comp["c.jsx_snippet"])

        raw_styles = self._q(
            "MATCH (c:Component {name:$n})-[:HAS_STYLE]->(s:Style) "
            "RETURN s.state, s.property, s.value, s.media ORDER BY s.state, s.property",
            {"n": resolved},
        )
        # `media` (C35) is orthogonal to `state`: an unconditional style
        # (media="") buckets by state as before; a viewport-conditional one
        # buckets separately by its raw @media condition, never mixed into
        # styles_by_state — mixing them would let a ≤600px-only value read
        # as if it were the component's actual default.
        styles_by_state: dict[str, list[dict]] = {}
        responsive_styles_by_media: dict[str, list[dict]] = {}
        for s in raw_styles:
            entry = {"property": s["s.property"], "value": s["s.value"]}
            media = s.get("s.media") or ""
            if media:
                responsive_styles_by_media.setdefault(media, []).append(entry)
            else:
                styles_by_state.setdefault(s["s.state"], []).append(entry)

        tokens = self._q(
            "MATCH (c:Component {name:$n})-[:USES_TOKEN]->(t:Token) "
            "RETURN t.label, t.value, t.category ORDER BY t.category",
            {"n": resolved},
        )
        texts = self._q(
            "MATCH (c:Component {name:$n})-[:COMP_HAS_TEXT]->(t:UIText) "
            "RETURN t.content, t.text_type, t.element ORDER BY t.text_type",
            {"n": resolved},
        )
        interactions = self._q(
            "MATCH (c:Component {name:$n})-[:HAS_INTERACTION]->(i:Interaction) "
            "RETURN i.trigger, i.css_prop, i.from_val, i.to_val, i.transition",
            {"n": resolved},
        )
        props = self.get_component_props(resolved)

        logger.debug(
            "reader: get_component_spec(%s) — %d styles, %d tokens, %d interactions, %d props",
            resolved, len(raw_styles), len(tokens), len(interactions), len(props),
        )

        return {
            **comp,
            "styles_by_state": styles_by_state,
            "responsive_styles_by_media": responsive_styles_by_media,
            "tokens":          tokens,
            "texts":           texts[:15],
            "interactions":    interactions,
            "children":        self.get_component_children(resolved),
            "parents":         self.get_component_parents(resolved),
            "screens_using":   self.find_screens_using_comp_transitively(resolved),
            "props":           props,
        }

    def get_component_props(self, name: str) -> list[dict]:
        """
        Return declared props for a component via HAS_PROP.

        Each dict has keys: prop_name, default_value, component_name.
        An empty default_value means the prop is required (no default declared).
        Returns an empty list when the component has no declared props or doesn't exist.
        """
        resolved = self._fuzzy_find_component(name)
        if resolved is None:
            return []
        rows = self._q(
            "MATCH (c:Component {name:$n})-[:HAS_PROP]->(p:ComponentProp) "
            "RETURN p.prop_name AS prop_name, p.default_value AS default_value, "
            "       p.component_name AS component_name "
            "ORDER BY p.prop_name",
            {"n": resolved},
        )
        logger.debug("reader: get_component_props(%s) — %d props", resolved, len(rows))
        return rows

    def component_exists(self, name: str) -> bool:
        """Return whether a Component node with this exact name exists."""
        rows = self._q("MATCH (c:Component {name:$n}) RETURN c.name", {"n": name})
        return bool(rows)

    def get_component_children(self, name: str) -> list[str]:
        """
        Return names of components directly contained by this component
        (via CONTAINS), in sibling render order (order_index) — the order
        they actually appear in the source JSX, not alphabetical.
        """
        rows = self._q(
            "MATCH (p:Component {name:$n})-[r:CONTAINS]->(c:Component) "
            "RETURN c.name ORDER BY r.order_index",
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

    def get_component_full(self, name: str) -> dict | None:
        """
        Return the full component tree rooted at `name`: the resolved root
        plus every descendant reachable via CONTAINS (3 levels deep — the
        same depth already used throughout this file for screen-level
        closures, a literal bound Kuzu requires on variable-length
        patterns), each with its own styles/tokens/texts/interactions/props
        and ordered children. One call to reconstruct a complex component
        without cascading through get_component_children for every
        grandchild. Returns None when the root isn't found.
        """
        resolved = self._fuzzy_find_component(name)
        if resolved is None:
            return None

        descendant_rows = self._q(
            "MATCH (root:Component {name:$n})-[:CONTAINS*1..3]->(c:Component) "
            "RETURN DISTINCT c.name",
            {"n": resolved},
        )
        names = [resolved] + [r["c.name"] for r in descendant_rows]

        comp_rows = self._q(
            "UNWIND $names AS cn "
            "MATCH (c:Component {name:cn}) "
            "RETURN c.name, c.comp_type, c.jsx_snippet, c.occurrence, c.classes, "
            "c.truncated_fields "
            "ORDER BY c.name",
            {"names": names},
        )
        for row in comp_rows:
            row["c.jsx_snippet"] = self._resolve_icons(row["c.jsx_snippet"] or "")

        comp_style_rows = self._q(
            # media = '' guard: see get_component's identical comment (C35) —
            # this tool doesn't partition responsive styles out either.
            "UNWIND $names AS cn "
            "MATCH (c:Component {name:cn})-[:HAS_STYLE]->(st:Style) "
            "WHERE st.media = '' "
            "RETURN c.name AS comp_name, st.state AS state, "
            "st.property AS property, st.value AS value "
            "ORDER BY c.name, st.state, st.property",
            {"names": names},
        )
        comp_token_rows = self._q(
            "UNWIND $names AS cn "
            "MATCH (c:Component {name:cn})-[:USES_TOKEN]->(t:Token) "
            "RETURN c.name AS comp_name, t.label AS label, t.value AS value, "
            "t.category AS category ORDER BY c.name, t.category",
            {"names": names},
        )
        comp_text_rows = self._q(
            "UNWIND $names AS cn "
            "MATCH (c:Component {name:cn})-[:COMP_HAS_TEXT]->(t:UIText) "
            "RETURN c.name AS comp_name, t.content AS content, t.text_type AS text_type "
            "ORDER BY c.name, t.text_type",
            {"names": names},
        )
        comp_inter_rows = self._q(
            "UNWIND $names AS cn "
            "MATCH (c:Component {name:cn})-[:HAS_INTERACTION]->(i:Interaction) "
            "RETURN c.name AS comp_name, i.trigger AS trigger, i.css_prop AS css_prop, "
            "i.from_val AS from_val, i.to_val AS to_val, i.transition AS transition",
            {"names": names},
        )
        comp_prop_rows = self._q(
            "UNWIND $names AS cn "
            "MATCH (c:Component {name:cn})-[:HAS_PROP]->(p:ComponentProp) "
            "RETURN c.name AS comp_name, p.prop_name AS prop_name, p.default_value AS default_value "
            "ORDER BY c.name, p.prop_name",
            {"names": names},
        )
        # Children ordered by sibling render order (order_index), restricted
        # to edges within this tree — a child outside the 3-level closure
        # (deeper than we expanded) is still named here even though it isn't
        # itself expanded, same "named but not inlined" trade-off
        # get_screen_full already makes at its own depth limit.
        edge_rows = self._q(
            "UNWIND $names AS pn "
            "MATCH (p:Component {name:pn})-[r:CONTAINS]->(c:Component) "
            "RETURN p.name AS parent_name, c.name AS child_name "
            "ORDER BY p.name, r.order_index",
            {"names": names},
        )

        styles_by_comp: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
        for r in comp_style_rows:
            styles_by_comp[r["comp_name"]][r["state"]].append(
                {"property": r["property"], "value": r["value"]}
            )
        tokens_by_comp: dict[str, list[dict]] = defaultdict(list)
        for r in comp_token_rows:
            tokens_by_comp[r["comp_name"]].append(
                {"label": r["label"], "value": r["value"], "category": r["category"]}
            )
        texts_by_comp: dict[str, list[dict]] = defaultdict(list)
        for r in comp_text_rows:
            texts_by_comp[r["comp_name"]].append(
                {"content": r["content"], "text_type": r["text_type"]}
            )
        interactions_by_comp: dict[str, list[dict]] = defaultdict(list)
        for r in comp_inter_rows:
            interactions_by_comp[r["comp_name"]].append({
                "trigger": r["trigger"], "css_prop": r["css_prop"],
                "from_val": r["from_val"], "to_val": r["to_val"], "transition": r["transition"],
            })
        props_by_comp: dict[str, list[dict]] = defaultdict(list)
        for r in comp_prop_rows:
            props_by_comp[r["comp_name"]].append(
                {"prop_name": r["prop_name"], "default_value": r["default_value"]}
            )
        children_by_comp: dict[str, list[str]] = defaultdict(list)
        for r in edge_rows:
            children_by_comp[r["parent_name"]].append(r["child_name"])

        components = []
        for comp in comp_rows:
            cname = comp["c.name"]
            components.append({
                "name":              cname,
                "comp_type":         comp["c.comp_type"],
                "jsx_snippet":       comp["c.jsx_snippet"] or "",
                "occurrence":        comp["c.occurrence"],
                "classes":           comp["c.classes"] or "",
                "truncated_fields":  (comp.get("c.truncated_fields") or "").split(",") if comp.get("c.truncated_fields") else [],
                "styles_by_state":   dict(styles_by_comp.get(cname, {})),
                "tokens":            tokens_by_comp.get(cname, []),
                "texts":             texts_by_comp.get(cname, []),
                "interactions":      interactions_by_comp.get(cname, []),
                "props":             props_by_comp.get(cname, []),
                "children":          children_by_comp.get(cname, []),
            })

        return {"root": resolved, "components": components}

    def get_build_diff(self) -> dict | None:
        """
        Return this document's most recent build diff — screens/components
        added or removed relative to the build before it — read from its
        <database>.state.json. This is the same diff `design-graph ... --diff`
        would log, kept even when --diff wasn't passed on that build, so an
        agent can ask "what changed since the last build" without comparing
        two Kuzu databases from scratch.

        Returns None when this reader wasn't given a state_path (e.g. built
        directly in a test without one), the file doesn't exist, or it
        predates this field.
        """
        if self._state_path is None or not self._state_path.exists():
            return None
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            diff = data.get("last_diff") if isinstance(data, dict) else None
            return diff if isinstance(diff, dict) else None
        except Exception as exc:  # noqa: BLE001
            logger.debug("reader: could not read build diff from %s: %s", self._state_path, exc)
            return None

    def find_screens_using_comp_transitively(self, comp_name: str) -> list[str]:
        """
        Return screen names that use comp_name directly or via CONTAINS composition
        (up to 3 levels deep).

        Traversal: Screen -[USES_COMPONENT]-> AnyComponent -[CONTAINS*0..3]-> Target.
        CONTAINS*0 covers direct usage (component used by screen itself).
        """
        rows = self._q(
            "MATCH (s:Screen)-[:USES_COMPONENT]->(p:Component)"
            "-[:CONTAINS*0..3]->(c:Component {name:$n}) "
            "RETURN DISTINCT s.name ORDER BY s.name",
            {"n": comp_name},
        )
        logger.debug(
            "reader: find_screens_transitively(%s) → %d screens",
            comp_name,
            len(rows),
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
        section_id = sec["sec.id"]

        # Canonical styles come from graph nodes (SECTION_HAS_STYLE);
        # fall back to styles_json blob for older graphs that lack the relationship.
        graph_styles = self.get_section_styles(section_id)
        if graph_styles:
            styles = {s["property"]: s["value"] for s in graph_styles}
        else:
            styles = json.loads(sec["sec.styles_json"] or "{}")

        # Canonical texts come from UIText nodes (SECTION_HAS_TEXT);
        # fall back to texts_json blob for backward compatibility.
        graph_texts = self.get_section_texts(section_id)
        if graph_texts:
            texts = [t["content"] for t in graph_texts]
        else:
            texts = json.loads(sec["sec.texts_json"] or "[]")

        return {
            "id":               section_id,
            "name":             sec["sec.name"],
            "detection_method": sec["sec.detection_method"],
            "styles":           styles,
            "component_refs":   json.loads(sec["sec.components_json"] or "[]"),
            "texts":            texts,
            "jsx_snippet":      self._resolve_icons(sec["sec.jsx_snippet"] or ""),
        }

    def get_section_texts(self, section_id: str) -> list[dict]:
        """
        Return text content entries for a section container via SECTION_HAS_TEXT.

        Each dict has key: content.
        Returns an empty list when the section has no texts or doesn't exist.
        """
        return self._q(
            "MATCH (sec:Section {id:$sid})-[:SECTION_HAS_TEXT]->(t:UIText) "
            "RETURN t.content AS content ORDER BY t.content",
            {"sid": section_id},
        )

    def get_section_styles(self, section_id: str) -> list[dict]:
        """
        Return style property/value pairs for a section container via SECTION_HAS_STYLE.

        Each dict has keys: property, value.
        Returns an empty list when the section has no container styles or doesn't exist.
        """
        rows = self._q(
            "MATCH (sec:Section {id:$sid})-[:SECTION_HAS_STYLE]->(s:Style) "
            "RETURN s.property AS property, s.value AS value "
            "ORDER BY s.property",
            {"sid": section_id},
        )
        return rows

    # ── Tokens ────────────────────────────────────────────────────────────────

    def get_styles_with_tokens(self, comp_name: str) -> list[dict]:
        """
        Return styles for a component with their linked token (if any).
        Uses OPTIONAL MATCH so styles without STYLE_USES_TOKEN still appear,
        with token_* fields as None.

        Each dict: s.state, s.property, s.value, token_label, token_value, token_category.
        """
        resolved = self._fuzzy_find_component(comp_name)
        if not resolved:
            return []
        return self._q(
            # media = '' guard: see get_component's identical comment (C35).
            "MATCH (c:Component {name:$n})-[:HAS_STYLE]->(s:Style) "
            "WHERE s.media = '' "
            "OPTIONAL MATCH (s)-[:STYLE_USES_TOKEN]->(t:Token) "
            "RETURN s.state, s.property, s.value, "
            "       t.label AS token_label, t.value AS token_value, "
            "       t.category AS token_category "
            "ORDER BY s.state, s.property",
            {"n": resolved},
        )

    def get_tokens(self, category: str | None = None, screen: str | None = None) -> list[dict]:
        """
        Every token (optionally filtered by category), or — when screen is
        given — only the tokens actually reachable from that screen's own
        components. Without scoping, a token's usage count is ranked
        prototype-wide, so a canvas color used on one screen looks
        identical to one used everywhere; scoping answers "what does this
        specific screen use" instead of "what's popular overall".

        Expands through the same USES_COMPONENT → CONTAINS* closure
        find_token_usage's screen listing uses, so a token used only by a
        nested component still counts toward the screen that renders it.
        """
        if screen:
            where = "AND t.category=$cat " if category else ""
            params: dict = {"screen": screen}
            if category:
                params["cat"] = category
            return self._q(
                "MATCH (s:Screen {name:$screen})-[:USES_COMPONENT]->(top:Component)"
                "-[:CONTAINS*0..3]->(c:Component)-[:USES_TOKEN]->(t:Token) "
                f"WHERE true {where}"
                "RETURN DISTINCT t.category, t.label, t.value, t.usage "
                "ORDER BY t.category, t.usage DESC",
                params,
            )
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

    def list_texts(self) -> list[dict]:
        """
        Return every UIText node for cross-prototype search.

        UIText is the only entity type search() was silently skipping —
        component/section names and token labels are searchable, but the
        actual visible strings in the prototype (button labels, headings,
        messages) never were.
        """
        return self._q(
            "MATCH (t:UIText) RETURN t.id, t.content, t.text_type, t.source, t.element"
        )

    def find_token_usage(self, value: str) -> list[dict]:
        """
        Return tokens matching value/label with their using components and screens.

        Uses 3 queries instead of 1+2N: one to find matching tokens, one JOIN
        for all component-token links, one JOIN for all screen-token links.
        Grouping is done in Python.
        """
        tokens = self._q(
            "MATCH (t:Token) WHERE toLower(t.value) CONTAINS toLower($val) "
            "OR toLower(t.label) CONTAINS toLower($val) "
            "RETURN t.id, t.label, t.value, t.category",
            {"val": value},
        )
        if not tokens:
            return []

        # Single JOIN query for all component-token relationships
        comp_rows = self._q(
            "MATCH (c:Component)-[:USES_TOKEN]->(t:Token) "
            "WHERE toLower(t.value) CONTAINS toLower($val) "
            "OR toLower(t.label) CONTAINS toLower($val) "
            "RETURN t.id AS token_id, c.name AS comp_name, c.comp_type AS comp_type",
            {"val": value},
        )

        # Single JOIN query for all screen-token relationships — expanded to
        # the CONTAINS closure so a token used only by a nested component
        # (e.g. PriceTag inside CartItem) still reports the screen that
        # renders it (same *0..3 depth used throughout get_screen_full).
        screen_rows = self._q(
            "MATCH (s:Screen)-[:USES_COMPONENT]->(top:Component)"
            "-[:CONTAINS*0..3]->(c:Component) "
            "WITH DISTINCT s, c "
            "MATCH (c)-[:USES_TOKEN]->(t:Token) "
            "WHERE toLower(t.value) CONTAINS toLower($val) "
            "OR toLower(t.label) CONTAINS toLower($val) "
            "RETURN DISTINCT t.id AS token_id, s.name AS screen_name",
            {"val": value},
        )

        # Group by token id in Python
        comps_by_token:   dict[str, list[dict]] = defaultdict(list)
        screens_by_token: dict[str, list[str]]  = defaultdict(list)

        for row in comp_rows:
            comps_by_token[row["token_id"]].append(
                {"c.name": row["comp_name"], "c.comp_type": row["comp_type"]}
            )
        for row in screen_rows:
            screens_by_token[row["token_id"]].append(row["screen_name"])

        return [
            {
                **tok,
                "components": comps_by_token[tok["t.id"]],
                "screens":    screens_by_token[tok["t.id"]],
            }
            for tok in tokens
        ]

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
        """
        A Component's jsx_snippet, or — when no Component of that name
        exists — the jsx_snippet of a Screen by that name. A full-page
        overlay shell (ItemEditorV6) is classified as a Screen and
        deliberately never also extracted as a Component (a screen
        boundary is never double-counted as a component), so without this
        fallback its own root JSX — the shell around its children — would
        never be reachable through this call at all.
        """
        comp_rows = self._q(
            "MATCH (c:Component {name:$n}) RETURN c.jsx_snippet, c.comp_type",
            {"n": name},
        )
        if comp_rows and comp_rows[0].get("c.jsx_snippet"):
            return self._resolve_icons(comp_rows[0]["c.jsx_snippet"])

        screen_rows = self._q(
            "MATCH (s:Screen {name:$n}) RETURN s.jsx_snippet", {"n": name},
        )
        if screen_rows and screen_rows[0].get("s.jsx_snippet"):
            return self._resolve_icons(screen_rows[0]["s.jsx_snippet"])
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
                "MATCH (s:Screen)-[:USES_COMPONENT]->(top:Component)"
                "-[:CONTAINS*0..3]->(c:Component)-[:USES_TOKEN]->(t:Token {id:$tid}) "
                "RETURN DISTINCT s.name",
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

    def get_health_metrics(self) -> dict:
        """Return relational coverage and token-category distribution."""
        category_rows = self._q(
            "MATCH (t:Token) RETURN t.category, count(t) AS total ORDER BY t.category"
        )
        screen_rows = self._q(
            "MATCH (s:Screen) WHERE EXISTS { MATCH (s)-[:USES_COMPONENT]->(:Component) } "
            "RETURN count(s) AS total"
        )
        component_rows = self._q(
            "MATCH (c:Component) WHERE EXISTS { MATCH (:Screen)-[:USES_COMPONENT]->(c) } "
            "RETURN count(c) AS total"
        )
        return {
            "token_categories": {
                row.get("t.category", "unknown"): int(row.get("total", 0))
                for row in category_rows
            },
            "screens_with_components": int(screen_rows[0].get("total", 0)) if screen_rows else 0,
            "components_with_screens": int(component_rows[0].get("total", 0)) if component_rows else 0,
        }

    # ── Full screen composite query ───────────────────────────────────────────

    def get_screen_full(self, name: str) -> dict | None:
        """
        Return everything needed to implement a screen in one call.

        Issues a bounded set of JOIN queries (O(1) round-trips regardless of
        component count) and assembles the result in Python.  The returned dict
        contains:

        - Screen metadata (name, component_count, sections_count)
        - sections: list of dicts with styles, texts, component_refs, jsx_snippet
        - components: list of dicts with styles_by_state, tokens, texts,
                      interactions, props, children, jsx_snippet
        - layout_profiles: list of LayoutProfile dicts (display, flex, spacing…)

        Section styles come from SECTION_HAS_STYLE nodes (canonical) with a
        fallback to the styles_json blob for older graphs.
        Section texts come from SECTION_HAS_TEXT nodes with a fallback to texts_json.
        """
        resolved = self._fuzzy_find_screen(name)
        if not resolved:
            return None

        # Q1: Screen metadata
        screen_rows = self._q(
            "MATCH (s:Screen {name:$n}) "
            "RETURN s.name, s.component_count, s.sections_count",
            {"n": resolved},
        )
        if not screen_rows:
            return None
        s = screen_rows[0]

        # Q2: All sections
        section_rows = self._q(
            "MATCH (s:Screen {name:$n})-[:HAS_SECTION]->(sec:Section) "
            "RETURN sec.id, sec.name, sec.components_json, sec.texts_json, "
            "       sec.styles_json, sec.jsx_snippet, sec.detection_method",
            {"n": resolved},
        )
        for row in section_rows:
            row["sec.jsx_snippet"] = self._resolve_icons(row["sec.jsx_snippet"] or "")

        # Q3: Section styles — canonical source (SECTION_HAS_STYLE)
        sec_style_rows = self._q(
            "MATCH (s:Screen {name:$n})-[:HAS_SECTION]->(sec:Section)"
            "-[:SECTION_HAS_STYLE]->(st:Style) "
            "RETURN sec.id AS section_id, st.property AS property, st.value AS value",
            {"n": resolved},
        )

        # Q4: Section texts — canonical source (SECTION_HAS_TEXT)
        sec_text_rows = self._q(
            "MATCH (s:Screen {name:$n})-[:HAS_SECTION]->(sec:Section)"
            "-[:SECTION_HAS_TEXT]->(t:UIText) "
            "RETURN sec.id AS section_id, t.content AS content",
            {"n": resolved},
        )

        # Q5: All components used by this screen, expanded to the full nested
        # CONTAINS closure (not just direct USES_COMPONENT) — a component only
        # reachable by following CONTAINS from a top-level one is still
        # inlined here with its own styles/tokens/props, not just named in
        # its parent's `children` list. *0..3 matches the depth already used
        # by get_component_spec/find_screens_using_comp_transitively.
        comp_rows = self._q(
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(top:Component)"
            "-[:CONTAINS*0..3]->(c:Component) "
            "RETURN DISTINCT c.name, c.comp_type, c.jsx_snippet, c.occurrence, c.classes, "
            "c.truncated_fields "
            "ORDER BY c.name",
            {"n": resolved},
        )
        for row in comp_rows:
            row["c.jsx_snippet"] = self._resolve_icons(row["c.jsx_snippet"] or "")

        # Q6: Component styles — all states via single JOIN (also used for layout profiles)
        #
        # Kuzu requires a `WITH DISTINCT` boundary between a variable-length
        # hop and any further pattern chained after it — a component reached
        # via multiple CONTAINS paths must be deduped *before* joining its
        # styles, or the join itself would duplicate rows.
        comp_style_rows = self._q(
            # media = '' guard: see get_component's identical comment (C35) —
            # this feeds layout_by_comp below via plain dict assignment
            # (last-row-wins), so a leaked responsive row could silently
            # replace the true default width/padding/etc. depending on scan
            # order, not on which one is actually unconditional.
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(top:Component)"
            "-[:CONTAINS*0..3]->(c:Component) "
            "WITH DISTINCT c "
            "MATCH (c)-[:HAS_STYLE]->(st:Style) "
            "WHERE st.media = '' "
            "RETURN c.name AS comp_name, st.state AS state, "
            "       st.property AS property, st.value AS value "
            "ORDER BY c.name, st.state, st.property",
            {"n": resolved},
        )

        # Q7: Component tokens
        comp_token_rows = self._q(
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(top:Component)"
            "-[:CONTAINS*0..3]->(c:Component) "
            "WITH DISTINCT c "
            "MATCH (c)-[:USES_TOKEN]->(t:Token) "
            "RETURN c.name AS comp_name, t.label AS label, "
            "       t.value AS value, t.category AS category "
            "ORDER BY c.name, t.category",
            {"n": resolved},
        )

        # Q8: Component texts
        comp_text_rows = self._q(
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(top:Component)"
            "-[:CONTAINS*0..3]->(c:Component) "
            "WITH DISTINCT c "
            "MATCH (c)-[:COMP_HAS_TEXT]->(t:UIText) "
            "RETURN c.name AS comp_name, t.content AS content, "
            "       t.text_type AS text_type, t.element AS element "
            "ORDER BY c.name, t.text_type",
            {"n": resolved},
        )

        # Q9: Component interactions
        comp_interact_rows = self._q(
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(top:Component)"
            "-[:CONTAINS*0..3]->(c:Component) "
            "WITH DISTINCT c "
            "MATCH (c)-[:HAS_INTERACTION]->(i:Interaction) "
            "RETURN c.name AS comp_name, i.trigger AS trigger, i.css_prop AS css_prop, "
            "       i.from_val AS from_val, i.to_val AS to_val, i.transition AS transition",
            {"n": resolved},
        )

        # Q10: Component props
        comp_prop_rows = self._q(
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(top:Component)"
            "-[:CONTAINS*0..3]->(c:Component) "
            "WITH DISTINCT c "
            "MATCH (c)-[:HAS_PROP]->(p:ComponentProp) "
            "RETURN c.name AS comp_name, p.prop_name AS prop_name, "
            "       p.default_value AS default_value "
            "ORDER BY c.name, p.prop_name",
            {"n": resolved},
        )

        # Q11: Component children (CONTAINS) — one more hop past the closure
        # bound above, so every component in `comp_rows` reports its own
        # direct children, not just the screen's top-level components.
        # Ordered by order_index (sibling render order), not child name —
        # children_by_comp below preserves this as the list order.
        comp_children_rows = self._q(
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(top:Component)"
            "-[:CONTAINS*0..3]->(parent:Component) "
            "WITH DISTINCT parent "
            "MATCH (parent)-[r:CONTAINS]->(child:Component) "
            "RETURN parent.name AS parent_name, child.name AS child_name "
            "ORDER BY parent.name, r.order_index",
            {"n": resolved},
        )

        logger.debug(
            "reader: get_screen_full(%s) — %d sections, %d components",
            resolved, len(section_rows), len(comp_rows),
        )
        return _assemble_screen_full(
            screen_meta=s,
            section_rows=section_rows,
            sec_style_rows=sec_style_rows,
            sec_text_rows=sec_text_rows,
            comp_rows=comp_rows,
            comp_style_rows=comp_style_rows,
            comp_token_rows=comp_token_rows,
            comp_text_rows=comp_text_rows,
            comp_interact_rows=comp_interact_rows,
            comp_prop_rows=comp_prop_rows,
            comp_children_rows=comp_children_rows,
        )

    # ── Layout profiles ───────────────────────────────────────────────────────

    def get_component_layout_profile(self, name: str) -> dict | None:
        """
        Return a LayoutProfile dict for a component filtered to default-state
        layout CSS properties only (no visual properties like color or border).

        Returns None when the component cannot be found.
        Visual properties (backgroundColor, borderColor, etc.) are excluded;
        they live in the component's style nodes and are available via get_component().
        """
        resolved = self._fuzzy_find_component(name)
        if resolved is None:
            return None

        style_rows = self._q(
            # media = '' guard (C35): layout_props below is a plain dict
            # keyed by property — a leaked responsive row would silently
            # replace the true default value, last-row-wins, unrelated to
            # which one is actually unconditional.
            "MATCH (c:Component {name:$n})-[:HAS_STYLE]->(s:Style) "
            "WHERE s.state = 'default' AND s.media = '' "
            "RETURN s.property, s.value",
            {"n": resolved},
        )
        layout_props = {
            row["s.property"]: row["s.value"]
            for row in style_rows
            if row["s.property"] in LAYOUT_CSS_PROPERTIES
        }
        logger.debug(
            "reader: get_component_layout_profile(%s) — %d layout props",
            resolved, len(layout_props),
        )
        return _build_layout_profile(resolved, layout_props)

    def get_screen_layout(self, screen_name: str) -> list[dict]:
        """
        Return a LayoutProfile dict for every component used directly by a screen.

        Uses 2 queries (one for component names, one JOIN for all styles) so the
        call cost is O(1) database round-trips regardless of how many components
        the screen has.
        """
        resolved = self._fuzzy_find_screen(screen_name)
        if resolved is None:
            return []

        comp_rows = self._q(
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(c:Component) "
            "RETURN c.name ORDER BY c.name",
            {"n": resolved},
        )
        if not comp_rows:
            return []

        style_rows = self._q(
            # media = '' guard: same reasoning as get_component_layout_profile (C35).
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(c:Component)"
            "-[:HAS_STYLE]->(st:Style) "
            "WHERE st.state = 'default' AND st.media = '' "
            "RETURN c.name AS comp_name, st.property AS prop, st.value AS val",
            {"n": resolved},
        )

        by_comp: dict[str, dict[str, str]] = defaultdict(dict)
        for row in style_rows:
            if row["prop"] in LAYOUT_CSS_PROPERTIES:
                by_comp[row["comp_name"]][row["prop"]] = row["val"]

        logger.debug(
            "reader: get_screen_layout(%s) — %d components, %d with layout styles",
            resolved, len(comp_rows), len(by_comp),
        )
        return [
            _build_layout_profile(row["c.name"], by_comp.get(row["c.name"], {}))
            for row in comp_rows
        ]

    # ── Fuzzy name resolution ─────────────────────────────────────────────────

    def _fuzzy_find_screen(self, hint: str) -> str | None:
        # Fast path: most calls arrive with a name already exact (e.g. copied
        # from list_screens) — a PK lookup avoids pulling every screen name
        # into Python just to confirm what's already an exact match.
        exact = self._q("MATCH (s:Screen {name:$n}) RETURN s.name", {"n": hint})
        if exact:
            return exact[0]["s.name"]
        all_screens = self._q("MATCH (s:Screen) RETURN s.name")
        names = [r["s.name"] for r in all_screens]
        return _fuzzy_match(hint, names)

    def _fuzzy_find_component(self, hint: str) -> str | None:
        exact = self._q("MATCH (c:Component {name:$n}) RETURN c.name", {"n": hint})
        if exact:
            return exact[0]["c.name"]
        all_comps = self._q("MATCH (c:Component) RETURN c.name")
        names = [r["c.name"] for r in all_comps]
        return _fuzzy_match(hint, names)

    # ── Icon expansion ────────────────────────────────────────────────────────

    def _resolve_icons(self, jsx_snippet: str) -> str:
        """
        Expand every {[icon:id]} reference in `jsx_snippet` back into the full
        SVG markup it stands for, via one batched lookup for however many
        distinct icons the snippet references.

        A snippet with no icon reference is returned unchanged with no query.
        A reference with no matching Icon node (should not happen against a
        graph built by this same codebase) is left as-is rather than dropped.
        """
        if not jsx_snippet or "{[icon:" not in jsx_snippet:
            return jsx_snippet

        ids = sorted(set(RE_ICON_MARKER.findall(jsx_snippet)))
        rows = self._q(
            "MATCH (i:Icon) WHERE i.id IN $ids RETURN i.id, i.markup", {"ids": ids},
        )
        markup_by_id = {row["i.id"]: row["i.markup"] for row in rows}
        return resolve_icon_markers(jsx_snippet, markup_by_id)

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


def _assemble_screen_full(
    *,
    screen_meta: dict,
    section_rows: list[dict],
    sec_style_rows: list[dict],
    sec_text_rows: list[dict],
    comp_rows: list[dict],
    comp_style_rows: list[dict],
    comp_token_rows: list[dict],
    comp_text_rows: list[dict],
    comp_interact_rows: list[dict],
    comp_prop_rows: list[dict],
    comp_children_rows: list[dict],
) -> dict:
    """
    Assemble the get_screen_full response dict from pre-fetched query results.

    All grouping is done in Python to avoid N+1 query patterns.
    Kept as a module-level function (not a method) to keep it unit-testable
    and to separate data assembly from query concerns.
    """
    # ── Section data ──────────────────────────────────────────────────────────
    sec_styles_by_id: dict[str, dict[str, str]] = defaultdict(dict)
    for r in sec_style_rows:
        sec_styles_by_id[r["section_id"]][r["property"]] = r["value"]

    sec_texts_by_id: dict[str, list[str]] = defaultdict(list)
    for r in sec_text_rows:
        sec_texts_by_id[r["section_id"]].append(r["content"])

    sections = []
    for sec in section_rows:
        sid    = sec["sec.id"]
        # Canonical source: graph nodes; fallback: JSON blob for older graphs
        styles = sec_styles_by_id.get(sid) or json.loads(sec["sec.styles_json"] or "{}")
        texts  = sec_texts_by_id.get(sid)  or json.loads(sec["sec.texts_json"]  or "[]")
        sections.append({
            "id":               sid,
            "name":             sec["sec.name"],
            "detection_method": sec["sec.detection_method"],
            "styles":           dict(styles),
            "component_refs":   json.loads(sec["sec.components_json"] or "[]"),
            "texts":            list(texts),
            "jsx_snippet":      sec["sec.jsx_snippet"] or "",
        })

    # ── Component data ────────────────────────────────────────────────────────
    styles_by_comp: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    layout_by_comp: dict[str, dict[str, str]]        = defaultdict(dict)
    for r in comp_style_rows:
        styles_by_comp[r["comp_name"]][r["state"]].append(
            {"property": r["property"], "value": r["value"]}
        )
        if r["state"] == "default" and r["property"] in LAYOUT_CSS_PROPERTIES:
            layout_by_comp[r["comp_name"]][r["property"]] = r["value"]

    tokens_by_comp: dict[str, list[dict]] = defaultdict(list)
    for r in comp_token_rows:
        tokens_by_comp[r["comp_name"]].append(
            {"label": r["label"], "value": r["value"], "category": r["category"]}
        )

    texts_by_comp: dict[str, list[dict]] = defaultdict(list)
    for r in comp_text_rows:
        texts_by_comp[r["comp_name"]].append(
            {"content": r["content"], "text_type": r["text_type"], "element": r["element"]}
        )

    interactions_by_comp: dict[str, list[dict]] = defaultdict(list)
    for r in comp_interact_rows:
        interactions_by_comp[r["comp_name"]].append({
            "trigger":    r["trigger"],
            "css_prop":   r["css_prop"],
            "from_val":   r["from_val"],
            "to_val":     r["to_val"],
            "transition": r["transition"],
        })

    props_by_comp: dict[str, list[dict]] = defaultdict(list)
    for r in comp_prop_rows:
        props_by_comp[r["comp_name"]].append(
            {"prop_name": r["prop_name"], "default_value": r["default_value"]}
        )

    children_by_comp: dict[str, list[str]] = defaultdict(list)
    for r in comp_children_rows:
        children_by_comp[r["parent_name"]].append(r["child_name"])

    components = []
    for comp in comp_rows:
        cname = comp["c.name"]
        components.append({
            "name":           cname,
            "comp_type":      comp["c.comp_type"],
            "jsx_snippet":    comp["c.jsx_snippet"] or "",
            "occurrence":     comp["c.occurrence"],
            "classes":        comp["c.classes"] or "",
            "truncated_fields": (comp.get("c.truncated_fields") or "").split(",") if comp.get("c.truncated_fields") else [],
            "styles_by_state": {
                state: entries
                for state, entries in styles_by_comp.get(cname, {}).items()
            },
            "tokens":       tokens_by_comp.get(cname, []),
            "texts":        texts_by_comp.get(cname, []),
            "interactions": interactions_by_comp.get(cname, []),
            "props":        props_by_comp.get(cname, []),
            "children":     children_by_comp.get(cname, []),
        })

    layout_profiles = [
        _build_layout_profile(comp["c.name"], layout_by_comp.get(comp["c.name"], {}))
        for comp in comp_rows
    ]

    return {
        "name":            screen_meta["s.name"],
        "component_count": screen_meta["s.component_count"],
        "sections_count":  screen_meta["s.sections_count"],
        "sections":        sections,
        "components":      components,
        "layout_profiles": layout_profiles,
    }


def _pixel_magnitude(value: str) -> float | None:
    """A bare or `px`-suffixed number's magnitude, or None for anything
    else (a percentage, a keyword like `auto`, an unparsable value) —
    those are never candidates for the decorative-dimension check."""
    v = value.strip()
    if not v or v.endswith("%"):
        return None
    if v.endswith("px"):
        v = v[:-2]
    try:
        return float(v)
    except ValueError:
        return None


def _is_decorative_dimension(value: str) -> bool:
    magnitude = _pixel_magnitude(value)
    return magnitude is not None and 0 < magnitude <= DECORATIVE_DIMENSION_MAX_PX


def _build_layout_profile(comp_name: str, layout_props: dict[str, str]) -> dict:
    """
    Build a normalised layout profile dict from a raw property→value map.

    First-class fields (display, width, flex_direction, …) are lifted to named
    keys with snake_case names.  Any remaining layout property that has no
    first-class key is collected in ``extra_layout``.

    width/height are hidden together when both are present and both read
    as a decorative-sized dimension (see DECORATIVE_DIMENSION_MAX_PX) —
    style capture has no notion of which JSX node within a component a
    style came from, so a tiny nested decoration's dimensions would
    otherwise be indistinguishable from the component's own real size.
    """
    hide_dimensions = (
        "width" in layout_props and "height" in layout_props
        and _is_decorative_dimension(layout_props["width"])
        and _is_decorative_dimension(layout_props["height"])
    )
    extra = {k: v for k, v in layout_props.items() if k not in _LAYOUT_FAST_PATH_PROPERTIES}
    return {
        "component_name":  comp_name,
        "display":         layout_props.get("display"),
        "position":        layout_props.get("position"),
        "width":           None if hide_dimensions else layout_props.get("width"),
        "height":          None if hide_dimensions else layout_props.get("height"),
        "padding":         layout_props.get("padding"),
        "padding_top":     layout_props.get("paddingTop"),
        "padding_right":   layout_props.get("paddingRight"),
        "padding_bottom":  layout_props.get("paddingBottom"),
        "padding_left":    layout_props.get("paddingLeft"),
        "margin":          layout_props.get("margin"),
        "margin_top":      layout_props.get("marginTop"),
        "margin_right":    layout_props.get("marginRight"),
        "margin_bottom":   layout_props.get("marginBottom"),
        "margin_left":     layout_props.get("marginLeft"),
        "flex_direction":  layout_props.get("flexDirection"),
        "align_items":     layout_props.get("alignItems"),
        "justify_content": layout_props.get("justifyContent"),
        "gap":             layout_props.get("gap"),
        "overflow":        layout_props.get("overflow"),
        "z_index":         layout_props.get("zIndex"),
        "extra_layout":    extra,
    }


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
