"""Tests for component_extractor single-pass — T06."""

import asyncio
from collections import Counter

import pytest

from design_graph.core.models import DesignToken
from design_graph.extraction.component_extractor import (
    extract_all_components,
    extract_component,
    infer_component_type,
    select_renderable_boundaries,
)
from design_graph.parsing.js_parser import find_all_boundaries
from design_graph.parsing.token_extractor import build_token_map

BTN_JS = """
function BtnPrimary() {
    return (
        <button
            className="btn-primary action-btn"
            style={{backgroundColor: '#ffb81c', padding: '8px', transition: 'all 0.2s ease'}}
            onMouseEnter={e => e.target.style.backgroundColor = '#f59e0b'}
            onMouseLeave={e => e.target.style.backgroundColor = '#ffb81c'}
        >
            Confirmar
        </button>
    )
}
"""

CARD_WITH_CHILDREN_JS = """
function RestCard() {
    return (
        <div className="rest-card">
            <Badge status="open" />
            <StarRating value={4} />
            <h3>Nome do Restaurante</h3>
            <button className="btn-primary">Pedir</button>
        </div>
    )
}
"""


class TestRenderableComponentSelection:
    def test_excludes_pascal_case_runtime_functions_without_visual_output(self):
        js = """
        function FiberNode() { return createNode(); }
        function SectionCard() { return (<div>Card</div>); }
        """
        selected = select_renderable_boundaries(js, find_all_boundaries(js))
        assert [boundary.name for boundary in selected] == ["SectionCard"]

    def test_includes_component_returning_react_fragment(self):
        js = "function TweakSection() { return (<> <div>Theme</div> </>); }"

        selected = select_renderable_boundaries(js, find_all_boundaries(js))

        assert [boundary.name for boundary in selected] == ["TweakSection"]


def _boundary(js: str, name: str):
    bounds = find_all_boundaries(js)
    return next(b for b in bounds if b.name == name)


class TestExtractComponent:
    def test_name_matches_boundary_name(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert comp.name == "BtnPrimary"

    def test_comp_type_inferred_as_button(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert comp.comp_type == "button"

    def test_jsx_snippet_captured(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert "button" in comp.jsx_snippet.lower()
        assert "Confirmar" in comp.jsx_snippet

    def test_svg_icon_is_deduplicated_into_marker(self):
        js = """
        function IconButton() {
            return (
                <button>
                    <svg viewBox="0 0 24 24"><path d="M12 2L2 7"/></svg>
                </button>
            )
        }
        """
        b = _boundary(js, "IconButton")
        comp = extract_component(js, b, 1, {})

        assert len(comp.icons) == 1
        assert "<svg" not in comp.jsx_snippet
        assert str(comp.icons[0]) in comp.jsx_snippet

    def test_default_style_found(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        default_props = {s.property for s in comp.styles if s.state == "default"}
        assert "backgroundColor" in default_props

    def test_hover_interaction_captured(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert any(i.trigger == "hover" for i in comp.interactions)

    def test_hover_has_from_and_to_values(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        hover = next(i for i in comp.interactions if i.trigger == "hover")
        assert hover.to_val != ""
        assert hover.from_val != ""

    def test_button_text_extracted(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert any("Confirmar" in t.content for t in comp.texts)


TOKEN_HOVER_JS = """
function OptRow({ o, on, color }) {
    return (
        <div
            style={{ background: '#2a2a2a' }}
            onMouseEnter={e => e.currentTarget.style.borderColor = C.red}
            onMouseLeave={e => e.currentTarget.style.borderColor = C.border2}
        >
            {o.label}
        </div>
    )
}
"""

EXPRESSION_HOVER_JS = """
function GroupCard({ color }) {
    return (
        <div
            onMouseEnter={e => e.currentTarget.style.background = color + '12'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
        >
            content
        </div>
    )
}
"""

FOCUS_TOKEN_JS = """
function TextInput() {
    return (
        <input onFocus={e => e.currentTarget.style.borderColor = C.accent} />
    )
}
"""


class TestHoverInteractionWithNonLiteralValues:
    """
    Real prototypes reference shared color tokens (C.red) or build the hover
    value from an expression (color + '12') far more often than they use a
    bare quoted literal. The old regex only matched quoted string literals,
    silently dropping the majority of hover/focus feedback in such codebases.
    """

    def test_hover_value_from_token_reference_is_captured(self):
        b = _boundary(TOKEN_HOVER_JS, "OptRow")
        comp = extract_component(TOKEN_HOVER_JS, b, 1, {})

        hover = next((i for i in comp.interactions if i.trigger == "hover"), None)
        assert hover is not None
        assert hover.css_prop == "borderColor"
        assert hover.to_val == "C.red"
        assert hover.from_val == "C.border2"

    def test_hover_value_from_expression_is_captured(self):
        b = _boundary(EXPRESSION_HOVER_JS, "GroupCard")
        comp = extract_component(EXPRESSION_HOVER_JS, b, 1, {})

        hover = next((i for i in comp.interactions if i.trigger == "hover"), None)
        assert hover is not None
        assert hover.to_val == "color + '12'"

    def test_literal_quoted_hover_value_still_unquoted(self):
        # Backward-compat guard: plain string literals must render the same
        # as before this pattern also matched identifiers/expressions.
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})

        hover = next(i for i in comp.interactions if i.trigger == "hover")
        assert "'" not in hover.to_val
        assert "'" not in hover.from_val

    def test_focus_value_from_token_reference_is_captured(self):
        b = _boundary(FOCUS_TOKEN_JS, "TextInput")
        comp = extract_component(FOCUS_TOKEN_JS, b, 1, {})

        focus = next((i for i in comp.interactions if i.trigger == "focus"), None)
        assert focus is not None
        assert focus.to_val == "C.accent"

    def test_hover_state_style_entry_uses_cleaned_value(self):
        b = _boundary(TOKEN_HOVER_JS, "OptRow")
        comp = extract_component(TOKEN_HOVER_JS, b, 1, {})

        hover_styles = [s for s in comp.styles if s.state == "hover"]
        assert any(s.value == "C.red" for s in hover_styles)

    def test_class_names_captured(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert "btn-primary" in comp.classes or "action-btn" in comp.classes

    def test_child_refs_captured(self):
        b = _boundary(CARD_WITH_CHILDREN_JS, "RestCard")
        comp = extract_component(CARD_WITH_CHILDREN_JS, b, 1, {})
        assert "Badge" in comp.child_refs
        assert "StarRating" in comp.child_refs

    def test_self_not_in_child_refs(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert "BtnPrimary" not in comp.child_refs

    def test_react_internals_not_in_child_refs(self):
        js = "function Comp() { return (<React.Fragment><div/></React.Fragment>) }"
        b = _boundary(js, "Comp")
        comp = extract_component(js, b, 1, {})
        assert "Fragment" not in comp.child_refs
        assert "React" not in comp.child_refs

    def test_occurrence_stored_correctly(self):
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 42, {})
        assert comp.occurrence == 42

    def test_token_map_accepted_without_error(self):
        token = DesignToken(id="c1", category="color",
                            label="primary", value="#ffb81c", usage=5)
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, build_token_map([token]))
        assert comp is not None

    def test_styles_capped_at_limit(self):
        many = " ".join(f"style={{{{p{i}: 'v{i}'}}}}" for i in range(60))
        js = f"function ManyStyles() {{ return (<div>{many}</div>) }}"
        b = _boundary(js, "ManyStyles")
        comp = extract_component(js, b, 1, {})
        assert len(comp.styles) <= 40

    def test_texts_capped_at_limit(self):
        texts = " ".join(f'"Texto {i} é longo"' for i in range(40))
        js = f"function TextHeavy() {{ return (<div>{texts}</div>) }}"
        b = _boundary(js, "TextHeavy")
        comp = extract_component(js, b, 1, {})
        assert len(comp.texts) <= 30

    def test_child_refs_contain_no_empty_strings(self):
        b = _boundary(CARD_WITH_CHILDREN_JS, "RestCard")
        comp = extract_component(CARD_WITH_CHILDREN_JS, b, 1, {})
        assert all(ref for ref in comp.child_refs)


MULTI_MUTATION_HOVER_JS = """
function OptionButton({ o, onPick }) {
    return (
        <button
            key={o.k}
            onClick={() => onPick(o.k)}
            style={{ background: '#2e2e2e', border: `1.5px solid ${C.border2}` }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = o.color; e.currentTarget.style.background = o.color + '0c'; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = C.border2; e.currentTarget.style.background = '#2e2e2e'; }}>
            {o.title}
        </button>
    )
}
"""

STATE_TOGGLE_HOVER_JS = """
function RestCard({ r, onSelect }) {
    const [hov, setHov] = useState(false);
    return (
        <div
            onClick={onSelect}
            onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
            style={{
                background: C.card, border: `1px solid ${hov ? C.accent + '55' : C.border}`,
                boxShadow: hov ? `0 0 0 1px ${C.accent}22, 0 4px 20px #0005` : 'none',
            }}>
            {r.name}
        </div>
    )
}
"""

STATE_TOGGLE_DIRECT_JS = """
function ItemCard({ item }) {
    const [h, setH] = useState(false);
    return (
        <div
            onMouseEnter={() => setH(true)} onMouseLeave={() => setH(false)}
            style={{
                border: `1px solid ${h ? C.border2 : C.border}`, transform: h ? 'translateY(-2px)' : 'none',
            }}>
            {item.name}
        </div>
    )
}
"""

TWO_SIBLINGS_SAME_STATE_NAME_JS = """
function CardA({ a }) {
    const [hov, setHov] = useState(false);
    return (
        <div onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
            style={{ border: hov ? C.red : C.border }}>
            {a.name}
        </div>
    )
}
function CardB({ b }) {
    const [hov, setHov] = useState(false);
    return (
        <div onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
            style={{ border: hov ? C.green : C.border }}>
            {b.name}
        </div>
    )
}
"""


class TestMultiStatementHoverHandlers:
    """
    Real prototypes almost always mutate more than one style property per
    handler (`e => { style.a = X; style.b = Y; }`). The old regex matched the
    literal text `onMouseEnter` once and captured only the first `style.` it
    found afterwards — every subsequent mutation in that same handler was
    silently dropped.
    """

    def test_both_mutated_properties_captured(self):
        b = _boundary(MULTI_MUTATION_HOVER_JS, "OptionButton")
        comp = extract_component(MULTI_MUTATION_HOVER_JS, b, 1, {})
        hover_props = {i.css_prop for i in comp.interactions if i.trigger == "hover"}
        assert hover_props == {"borderColor", "background"}

    def test_second_property_pairs_enter_with_matching_leave(self):
        b = _boundary(MULTI_MUTATION_HOVER_JS, "OptionButton")
        comp = extract_component(MULTI_MUTATION_HOVER_JS, b, 1, {})
        background = next(i for i in comp.interactions if i.css_prop == "background")
        assert background.to_val == "o.color + '0c'"
        assert background.from_val == "#2e2e2e"

    def test_single_statement_handler_still_works(self):
        # Backward-compat guard: BTN_JS has one mutation per handler, no braces.
        b = _boundary(BTN_JS, "BtnPrimary")
        comp = extract_component(BTN_JS, b, 1, {})
        assert any(i.trigger == "hover" for i in comp.interactions)


class TestStateToggleHoverInteractions:
    """
    A React boolean state var toggled by the handler, with the actual style
    change expressed as a ternary elsewhere in the JSX — not an imperative
    style.prop = value mutation. Covers ~20% of hover feedback in real
    prototypes (see docs/changes/C12-stateful-interactions/spec.md "Fora de
    escopo"), previously invisible to the graph entirely.
    """

    def test_ternary_inside_template_literal_captured(self):
        b = _boundary(STATE_TOGGLE_HOVER_JS, "RestCard")
        comp = extract_component(STATE_TOGGLE_HOVER_JS, b, 1, {})
        border = next((i for i in comp.interactions if i.css_prop == "border"), None)
        assert border is not None
        assert border.trigger == "hover"
        assert border.to_val == "C.accent + '55'"
        assert border.from_val == "C.border"

    def test_direct_ternary_value_captured(self):
        b = _boundary(STATE_TOGGLE_HOVER_JS, "RestCard")
        comp = extract_component(STATE_TOGGLE_HOVER_JS, b, 1, {})
        shadow = next((i for i in comp.interactions if i.css_prop == "boxShadow"), None)
        assert shadow is not None
        assert shadow.to_val == "`0 0 0 1px ${C.accent}22, 0 4px 20px #0005`"
        assert shadow.from_val == "none"

    def test_both_properties_from_same_state_var_captured(self):
        b = _boundary(STATE_TOGGLE_DIRECT_JS, "ItemCard")
        comp = extract_component(STATE_TOGGLE_DIRECT_JS, b, 1, {})
        props = {i.css_prop for i in comp.interactions if i.trigger == "hover"}
        assert props == {"border", "transform"}

    def test_hover_state_style_entry_recorded(self):
        b = _boundary(STATE_TOGGLE_DIRECT_JS, "ItemCard")
        comp = extract_component(STATE_TOGGLE_DIRECT_JS, b, 1, {})
        hover_styles = [s for s in comp.styles if s.state == "hover"]
        assert any(s.property == "transform" and s.value == "translateY(-2px)" for s in hover_styles)

    def test_reused_state_var_name_does_not_cross_contaminate_siblings(self):
        bounds = find_all_boundaries(TWO_SIBLINGS_SAME_STATE_NAME_JS)
        card_a = next(b for b in bounds if b.name == "CardA")
        card_b = next(b for b in bounds if b.name == "CardB")
        comp_a = extract_component(TWO_SIBLINGS_SAME_STATE_NAME_JS, card_a, 1, {})
        comp_b = extract_component(TWO_SIBLINGS_SAME_STATE_NAME_JS, card_b, 1, {})
        a_hover = next(i for i in comp_a.interactions if i.trigger == "hover")
        b_hover = next(i for i in comp_b.interactions if i.trigger == "hover")
        assert a_hover.to_val == "C.red"
        assert b_hover.to_val == "C.green"

    def test_no_false_positive_without_enter_leave_pair(self):
        # useState(bool) alone, with no onMouseEnter/onMouseLeave setter calls,
        # must not produce a hover interaction.
        js = """
        function Toggle() {
            const [on, setOn] = useState(false);
            return <div style={{ opacity: on ? 1 : 0.5 }} onClick={() => setOn(!on)} />;
        }
        """
        b = _boundary(js, "Toggle")
        comp = extract_component(js, b, 1, {})
        assert not any(i.trigger == "hover" for i in comp.interactions)


TOOLTIP_ICON_BUTTON_JS = """
function CloseButton({ onClose }) {
    return (
        <button onClick={onClose} title="Fechar" aria-label="Fechar modal">
            <XIcon />
        </button>
    )
}
"""


class TestTooltipTextExtraction:
    """
    Icon-only buttons carry their only textual signal in `title`/`aria-label` —
    without this, an agent can't distinguish always-visible content from
    hover-only supplementary text, and previously both landed under the same
    generic "label" text_type with no way to tell them apart.
    """

    def test_title_attribute_captured_as_tooltip(self):
        b = _boundary(TOOLTIP_ICON_BUTTON_JS, "CloseButton")
        comp = extract_component(TOOLTIP_ICON_BUTTON_JS, b, 1, {})
        tooltips = [t.content for t in comp.texts if t.text_type == "tooltip"]
        assert "Fechar" in tooltips

    def test_aria_label_attribute_captured_as_tooltip(self):
        b = _boundary(TOOLTIP_ICON_BUTTON_JS, "CloseButton")
        comp = extract_component(TOOLTIP_ICON_BUTTON_JS, b, 1, {})
        tooltips = [t.content for t in comp.texts if t.text_type == "tooltip"]
        assert "Fechar modal" in tooltips

    def test_tooltip_text_not_duplicated_as_generic_label(self):
        # Same content, same source → same id (EntityId.derive("txt", f"{source}_{content}")).
        # The tooltip pass must run before the generic UI-string pass so it wins
        # the dedup — otherwise "Fechar" would appear twice, once per type.
        b = _boundary(TOOLTIP_ICON_BUTTON_JS, "CloseButton")
        comp = extract_component(TOOLTIP_ICON_BUTTON_JS, b, 1, {})
        fechar_entries = [t for t in comp.texts if t.content == "Fechar"]
        assert len(fechar_entries) == 1
        assert fechar_entries[0].text_type == "tooltip"


class TestExtractAllComponents:
    def test_extracts_multiple_components(self):
        js = BTN_JS + CARD_WITH_CHILDREN_JS
        bounds = find_all_boundaries(js)
        occ = Counter(b.name for b in bounds)
        comps = asyncio.run(extract_all_components(js, bounds, occ, {}))
        names = {c.name for c in comps}
        assert "BtnPrimary" in names
        assert "RestCard" in names

    def test_no_duplicates_in_concurrent_run(self):
        funcs = "\n".join(
            f"function Component{i:02d}() {{ return (<div>comp{i}</div>) }}"
            for i in range(20)
        )
        bounds = find_all_boundaries(funcs)
        occ = Counter(b.name for b in bounds)
        comps = asyncio.run(extract_all_components(funcs, bounds, occ, {}))
        names = [c.name for c in comps]
        assert len(names) == len(set(names))

    def test_duplicate_definitions_are_consolidated_without_losing_variants(self):
        js = '''
        function SharedCard({ first }) {
            return (<div><AlphaCard /><button>First action</button></div>);
        }
        function SharedCard({ second }) {
            return (<section><BetaCard /><button>Second action</button></section>);
        }
        '''
        bounds = find_all_boundaries(js)

        components = asyncio.run(
            extract_all_components(js, bounds, Counter(b.name for b in bounds), {})
        )

        assert len(components) == 1
        component = components[0]
        assert component.occurrence == 2
        assert component.child_refs == ["AlphaCard", "BetaCard"]
        assert {prop.prop_name for prop in component.props} == {"first", "second"}
        assert "First action" in component.jsx_snippet
        assert "Second action" in component.jsx_snippet

    def test_duplicate_definitions_label_which_variant_actually_executes(self):
        # JS hoists `function Name(...)` declarations fully — a later
        # declaration of the same name in the same scope completely replaces
        # an earlier one, so only the last-declared variant ever runs.
        # Concatenating both without saying so lets an agent mistake
        # unreachable code for the real implementation.
        js = '''
        function SharedCard({ first }) {
            return (<div><AlphaCard /><button>First action</button></div>);
        }
        function SharedCard({ second }) {
            return (<section><BetaCard /><button>Second action</button></section>);
        }
        '''
        bounds = find_all_boundaries(js)
        components = asyncio.run(
            extract_all_components(js, bounds, Counter(b.name for b in bounds), {})
        )
        component = components[0]

        first_pos  = component.jsx_snippet.find("First action")
        second_pos = component.jsx_snippet.find("Second action")
        live_label_pos    = component.jsx_snippet.find("live")
        shadowed_label_pos = component.jsx_snippet.find("shadowed")

        assert -1 not in (first_pos, second_pos, live_label_pos, shadowed_label_pos)
        assert shadowed_label_pos < first_pos, "first-declared variant must be labeled shadowed"
        assert live_label_pos < second_pos, "last-declared variant must be labeled live"

    def test_works_with_concurrency_one(self):
        bounds = find_all_boundaries(BTN_JS)
        occ = Counter(b.name for b in bounds)
        comps = asyncio.run(extract_all_components(BTN_JS, bounds, occ, {}, concurrency=1))
        assert len(comps) >= 1

    def test_empty_boundaries_returns_empty(self):
        comps = asyncio.run(extract_all_components("", [], Counter(), {}))
        assert comps == []


# ── infer_component_type ──────────────────────────────────────────────────────

class TestInferComponentType:
    @pytest.mark.parametrize("name,expected", [
        ("BtnPrimary",       "button"),
        ("SaveButton",       "button"),
        ("ConfirmModal",     "modal"),
        ("AlertDialog",      "modal"),
        ("SectionCard",      "card"),
        ("RestCard",         "card"),
        ("KpiWidget",        "card"),
        ("LoginForm",        "form"),
        ("SearchInput",      "form"),
        ("TabBar",           "tab"),
        ("DonutChart",       "chart"),
        ("ProfileDrawer",    "navigation"),
        ("SidebarNav",       "navigation"),
        ("DarkToggle",       "toggle"),
        ("MenuItemRow",      "list-item"),
        ("StatusBadge",      "badge"),
        ("TagPill",          "badge"),
        ("HomePageScreen",   "screen"),
        ("GenericHelper",    "component"),
    ])
    def test_name_maps_to_expected_type(self, name, expected):
        assert infer_component_type(name) == expected

    def test_unknown_name_returns_component(self):
        assert infer_component_type("XyzAbc") == "component"

    def test_case_insensitive_matching(self):
        assert infer_component_type("BtnPrimary") == "button"

    def test_returns_string(self):
        assert isinstance(infer_component_type("AnyName"), str)

    # ── word-boundary bug fixes ───────────────────────────────────────────────
    @pytest.mark.parametrize("name,expected", [
        # Suffix determines type, not any substring hit in the full lowercased string
        ("ConfirmButton",    "button"),    # "confirm" substring must NOT win over "button" suffix
        ("PanelChart",       "chart"),     # "panel" substring must NOT win over "chart" suffix
        ("AlertButton",      "button"),    # "alert" substring must NOT win over "button" suffix
        ("DialogCard",       "card"),      # "dialog" substring must NOT win over "card" suffix
        ("SelectSection",    "card"),      # "select" (form) must NOT beat "section" (card) suffix
        ("ModalDrawer",      "navigation"), # modal prefix, drawer suffix → navigation wins
    ])
    def test_suffix_word_takes_precedence_over_prefix_substring(self, name, expected):
        assert infer_component_type(name) == expected, (
            f"infer_component_type({name!r}) returned {infer_component_type(name)!r}, "
            f"expected {expected!r}. Last word of PascalCase must determine type."
        )


# sanitize_jsx has its own dedicated test module: test_jsx_sanitizer.py
# (design_graph.extraction.jsx_sanitizer) — not tested here to avoid
# covering the same function from two different test-module "owners".
