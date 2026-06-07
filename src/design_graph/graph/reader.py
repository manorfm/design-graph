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

import kuzu

from design_graph.core.constants import LAYOUT_CSS_PROPERTIES, _LAYOUT_FAST_PATH_PROPERTIES

logger = logging.getLogger(__name__)


class GraphReader:
    """Read-only interface to a Kuzu design-graph database."""

    def __init__(self, conn: kuzu.Connection) -> None:
        self._conn = conn

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
            "RETURN c.name, c.comp_type, c.jsx_snippet, c.occurrence, c.classes",
            {"n": resolved},
        )
        if not rows:
            return None
        comp = rows[0]

        raw_styles = self._q(
            "MATCH (c:Component {name:$n})-[:HAS_STYLE]->(s:Style) "
            "RETURN s.state, s.property, s.value ORDER BY s.state, s.property",
            {"n": resolved},
        )
        styles_by_state: dict[str, list[dict]] = {}
        for s in raw_styles:
            bucket = styles_by_state.setdefault(s["s.state"], [])
            bucket.append({"property": s["s.property"], "value": s["s.value"]})

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
        screens_rows = self._q(
            "MATCH (s:Screen)-[:USES_COMPONENT]->(p:Component)"
            "-[:CONTAINS*0..3]->(c:Component {name:$n}) "
            "RETURN DISTINCT s.name ORDER BY s.name",
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
            "tokens":          tokens,
            "texts":           texts[:15],
            "interactions":    interactions,
            "children":        self.get_component_children(resolved),
            "parents":         self.get_component_parents(resolved),
            "screens_using":   [r["s.name"] for r in screens_rows],
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
            "jsx_snippet":      sec["sec.jsx_snippet"],
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
            "MATCH (c:Component {name:$n})-[:HAS_STYLE]->(s:Style) "
            "OPTIONAL MATCH (s)-[:STYLE_USES_TOKEN]->(t:Token) "
            "RETURN s.state, s.property, s.value, "
            "       t.label AS token_label, t.value AS token_value, "
            "       t.category AS token_category "
            "ORDER BY s.state, s.property",
            {"n": resolved},
        )

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

        # Single JOIN query for all screen-token relationships
        screen_rows = self._q(
            "MATCH (s:Screen)-[:USES_COMPONENT]->(c:Component)-[:USES_TOKEN]->(t:Token) "
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

        # Q5: All components used by this screen
        comp_rows = self._q(
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(c:Component) "
            "RETURN c.name, c.comp_type, c.jsx_snippet, c.occurrence, c.classes "
            "ORDER BY c.name",
            {"n": resolved},
        )

        # Q6: Component styles — all states via single JOIN (also used for layout profiles)
        comp_style_rows = self._q(
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(c:Component)"
            "-[:HAS_STYLE]->(st:Style) "
            "RETURN c.name AS comp_name, st.state AS state, "
            "       st.property AS property, st.value AS value "
            "ORDER BY c.name, st.state, st.property",
            {"n": resolved},
        )

        # Q7: Component tokens
        comp_token_rows = self._q(
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(c:Component)"
            "-[:USES_TOKEN]->(t:Token) "
            "RETURN c.name AS comp_name, t.label AS label, "
            "       t.value AS value, t.category AS category "
            "ORDER BY c.name, t.category",
            {"n": resolved},
        )

        # Q8: Component texts
        comp_text_rows = self._q(
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(c:Component)"
            "-[:COMP_HAS_TEXT]->(t:UIText) "
            "RETURN c.name AS comp_name, t.content AS content, "
            "       t.text_type AS text_type, t.element AS element "
            "ORDER BY c.name, t.text_type",
            {"n": resolved},
        )

        # Q9: Component interactions
        comp_interact_rows = self._q(
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(c:Component)"
            "-[:HAS_INTERACTION]->(i:Interaction) "
            "RETURN c.name AS comp_name, i.trigger AS trigger, i.css_prop AS css_prop, "
            "       i.from_val AS from_val, i.to_val AS to_val, i.transition AS transition",
            {"n": resolved},
        )

        # Q10: Component props
        comp_prop_rows = self._q(
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(c:Component)"
            "-[:HAS_PROP]->(p:ComponentProp) "
            "RETURN c.name AS comp_name, p.prop_name AS prop_name, "
            "       p.default_value AS default_value "
            "ORDER BY c.name, p.prop_name",
            {"n": resolved},
        )

        # Q11: Component children (CONTAINS)
        comp_children_rows = self._q(
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(parent:Component)"
            "-[:CONTAINS]->(child:Component) "
            "RETURN parent.name AS parent_name, child.name AS child_name "
            "ORDER BY parent.name, child.name",
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
            "MATCH (c:Component {name:$n})-[:HAS_STYLE]->(s:Style) "
            "WHERE s.state = 'default' "
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
            "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(c:Component)"
            "-[:HAS_STYLE]->(st:Style) "
            "WHERE st.state = 'default' "
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


def _build_layout_profile(comp_name: str, layout_props: dict[str, str]) -> dict:
    """
    Build a normalised layout profile dict from a raw property→value map.

    First-class fields (display, width, flex_direction, …) are lifted to named
    keys with snake_case names.  Any remaining layout property that has no
    first-class key is collected in ``extra_layout``.
    """
    extra = {k: v for k, v in layout_props.items() if k not in _LAYOUT_FAST_PATH_PROPERTIES}
    return {
        "component_name":  comp_name,
        "display":         layout_props.get("display"),
        "position":        layout_props.get("position"),
        "width":           layout_props.get("width"),
        "height":          layout_props.get("height"),
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
