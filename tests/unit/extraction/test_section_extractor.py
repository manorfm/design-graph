"""Tests for section_extractor — T08."""

import pytest

from design_graph.core.models import ExtractedScreen
from design_graph.extraction.section_extractor import extract_sections
from design_graph.parsing.css_class_resolver import CssRule
from design_graph.parsing.js_parser import find_all_boundaries

WITH_COMMENTS_JS = """
function RestaurantsPage() {
    return (
        <div>
            {/* ── Header ── */}
            <h1>Restaurantes</h1>
            <BtnFilter />

            {/* ── Lista ── */}
            <SectionCard item={a} />
            <SectionCard item={b} />

            {/* ── Footer ── */}
            <p>© 2024 iPede</p>
        </div>
    )
}
"""

WITHOUT_COMMENTS_JS = """
function RestaurantsPage() {
    return (
        <div>
            <div style={{padding: '24px', marginBottom: '16px'}}>
                <h1>Restaurantes em Destaque</h1>
                <BtnFilter />
            </div>
            <div style={{padding: '16px'}}>
                <SectionCard item={a} />
                <SectionCard item={b} />
            </div>
        </div>
    )
}
"""


def _boundary(js: str, name: str = "RestaurantsPage"):
    bounds = find_all_boundaries(js)
    return next(b for b in bounds if b.name == name)


def _screen(name: str = "RestaurantsPage") -> ExtractedScreen:
    return ExtractedScreen(name=name, component_refs=[], sections_count=0)


class TestCommentBasedSections:
    def test_finds_comment_sections(self):
        boundary = _boundary(WITH_COMMENTS_JS)
        sections = extract_sections(WITH_COMMENTS_JS, _screen(), boundary)
        names_lower = [s.name.lower() for s in sections]
        assert any("header" in n for n in names_lower)
        assert any("lista" in n for n in names_lower)

    def test_detection_method_is_comment(self):
        boundary = _boundary(WITH_COMMENTS_JS)
        sections = extract_sections(WITH_COMMENTS_JS, _screen(), boundary)
        assert all(s.detection_method == "comment" for s in sections)

    def test_filter_button_in_header_section(self):
        boundary = _boundary(WITH_COMMENTS_JS)
        sections = extract_sections(WITH_COMMENTS_JS, _screen(), boundary)
        header = next((s for s in sections if "header" in s.name.lower()), None)
        assert header is not None
        assert "BtnFilter" in header.component_refs

    def test_section_card_in_lista_section(self):
        boundary = _boundary(WITH_COMMENTS_JS)
        sections = extract_sections(WITH_COMMENTS_JS, _screen(), boundary)
        lista = next((s for s in sections if "lista" in s.name.lower()), None)
        assert lista is not None
        assert "SectionCard" in lista.component_refs

    def test_section_ids_are_unique(self):
        boundary = _boundary(WITH_COMMENTS_JS)
        sections = extract_sections(WITH_COMMENTS_JS, _screen(), boundary)
        ids = [s.id for s in sections]
        assert len(ids) == len(set(ids))

    def test_section_screen_field_matches_screen_name(self):
        boundary = _boundary(WITH_COMMENTS_JS)
        sections = extract_sections(WITH_COMMENTS_JS, _screen("RestaurantsPage"), boundary)
        for sec in sections:
            assert sec.screen == "RestaurantsPage"


class TestStructuralFallback:
    def test_fallback_triggers_when_no_comments(self):
        boundary = _boundary(WITHOUT_COMMENTS_JS)
        sections = extract_sections(WITHOUT_COMMENTS_JS, _screen(), boundary)
        assert len(sections) >= 1

    def test_detection_method_is_structural_or_none(self):
        boundary = _boundary(WITHOUT_COMMENTS_JS)
        sections = extract_sections(WITHOUT_COMMENTS_JS, _screen(), boundary)
        for sec in sections:
            assert sec.detection_method in ("structural", "none", "comment")

    def test_max_sections_from_structural_fallback(self):
        # Build a screen with many padding divs
        many_divs = "\n".join(
            f"<div style={{{{padding:'20px'}}}}>block{i}<Comp{i}/></div>"
            for i in range(20)
        )
        js = f"function BigPage() {{ return (<div>{many_divs}</div>) }}"
        bounds = find_all_boundaries(js)
        screen_b = next(b for b in bounds if b.name == "BigPage")
        screen = ExtractedScreen(name="BigPage", component_refs=[], sections_count=0)
        sections = extract_sections(js, screen, screen_b)
        assert len(sections) <= 8


class TestQualityFilter:
    def test_empty_section_not_created(self):
        js = """
        function EmptyPage() {
            return (
                <div>
                    {/* ── Empty ── */}
                </div>
            )
        }
        """
        bounds = find_all_boundaries(js)
        screen_b = next(b for b in bounds if b.name == "EmptyPage")
        screen = ExtractedScreen(name="EmptyPage", component_refs=[], sections_count=0)
        sections = extract_sections(js, screen, screen_b)
        for sec in sections:
            qualifies = (
                len(sec.component_refs) >= 1
                or len(sec.texts) >= 2
                or len(sec.styles) >= 3
            )
            assert qualifies, f"Empty section escaped quality filter: {sec.name}"

    def test_no_exception_on_screenless_js(self):
        js = "const x = 1;"
        bounds = find_all_boundaries(js)
        screen = ExtractedScreen(name="Missing", component_refs=[], sections_count=0)
        from design_graph.core.models import FunctionBoundary
        dummy = FunctionBoundary(name="Missing", start=0, body_start=0, end=0)
        result = extract_sections(js, screen, dummy)
        assert isinstance(result, list)


TEMPLATE_LITERAL_STYLE_JS = """
function RestaurantsPage() {
    return (
        <div>
            {/* ── Header ── */}
            <div style={{ padding: '24px', border: `1px solid ${C.border2}` }}>
                <h1>Restaurantes</h1>
                <BtnFilter />
            </div>
        </div>
    )
}
"""


LONG_DESCRIPTIVE_COMMENT_JS = """
function RestaurantDetail() {
    return (
        <div>
            {/* Quick KPIs */}
            <div style={{ display: 'grid', gap: '1px', marginTop: '18px' }}>
                {heroKpis.map(([l, v]) => <KpiCell key={l} label={l} value={v} />)}
            </div>

            {/* -- Painel unico: tabs + descricao + conteudo compartilham a mesma superficie -- */}
            <div style={{ background: C.card2 }}>
                <K.Tabs items={DETAIL_TABS} active={tab} onChange={setTab} />
                {tab === 'menus' && <PricingPageV6 lockRestaurantId={r.id} />}
                {tab === 'sectors' && <RestaurantSectorsView restaurantId={r.id} />}
            </div>

            {/* Edit modal */}
            {editing && <EditRestaurantModal r={r} />}
        </div>
    )
}
"""


class TestLongDescriptiveSectionComment:
    """
    Reproduces the RestaurantDetail screen from ipede_manager_v21.2: the
    real prototype separates "Quick KPIs" from the tabs+content panel with
    its own comment, `{/* -- Painel unico: tabs + descricao + conteudo
    compartilham a mesma superficie -- */}` — but RE_SECTION_COMMENT's name
    capture was hard-capped at 40 characters, so a comment whose text
    (sandwiched between the `--` decorators) ran longer than that failed to
    match at all. The panel's content — Tabs, PricingPageV6,
    RestaurantSectorsView, every other tab — then silently fell inside the
    *previous* section's block (Quick KPIs), and "Edit modal" became the
    very next detected boundary.
    """

    def test_long_comment_still_starts_its_own_section(self):
        boundary = _boundary(LONG_DESCRIPTIVE_COMMENT_JS, "RestaurantDetail")
        sections = extract_sections(LONG_DESCRIPTIVE_COMMENT_JS, _screen("RestaurantDetail"), boundary)
        assert len(sections) == 3

    def test_panel_content_not_absorbed_into_kpis_section(self):
        boundary = _boundary(LONG_DESCRIPTIVE_COMMENT_JS, "RestaurantDetail")
        sections = extract_sections(LONG_DESCRIPTIVE_COMMENT_JS, _screen("RestaurantDetail"), boundary)
        kpis = next(s for s in sections if "kpi" in s.name.lower())
        assert "PricingPageV6" not in kpis.component_refs
        assert "RestaurantSectorsView" not in kpis.component_refs

    def test_panel_section_gets_short_label_before_colon(self):
        boundary = _boundary(LONG_DESCRIPTIVE_COMMENT_JS, "RestaurantDetail")
        sections = extract_sections(LONG_DESCRIPTIVE_COMMENT_JS, _screen("RestaurantDetail"), boundary)
        panel = next(s for s in sections if "PricingPageV6" in s.component_refs)
        assert panel.name.lower() == "painel unico"
        assert len(panel.name) < 40


class TestSectionStyleSurvivesTemplateLiteral:
    """
    Same `[^}]{5,600}` block-boundary bug as component_extractor: a style
    block containing a template-literal interpolation (`${...}`) has a `}`
    that isn't the object's real closing brace. section_extractor used the
    same regex pair, so a section's own container style silently lost every
    property whenever any one of them held a template literal.
    """

    def test_all_properties_captured_despite_template_literal(self):
        boundary = _boundary(TEMPLATE_LITERAL_STYLE_JS)
        sections = extract_sections(TEMPLATE_LITERAL_STYLE_JS, _screen(), boundary)
        header = next(s for s in sections if "header" in s.name.lower())
        assert header.styles.get("padding") == "24px"
        assert header.styles.get("border") == "`1px solid ${C.border2}`"


AUDIT_ITEM_WITH_NESTED_CLASSES_JS = """
function HistoryView() {
    return (
        <div>
            {/* ── Audit item ── */}
            <div className="audit-item">
                <div className="audit-dot"><Icon name="history" /></div>
            </div>
        </div>
    )
}
"""


class TestSectionElementStyleAttribution:
    """
    A section styled entirely via CSS classes (no literal style={{}}
    objects) used to have every class's resolved properties flattened into
    one dict keyed only by property name — two classes contributing the
    SAME property (e.g. .audit-item{display:grid} and .audit-dot{display:
    flex}) collided, last-one-wins, with no way to tell which selector a
    surviving value came from. Reproduces the real "Audit item" bug from
    docs/changes/C36 (get_section("HistoryView", "Audit item") mixing
    .audit-item/.audit-rail/.audit-dot properties into one flat array).
    """

    def test_two_classes_with_same_property_both_survive_attributed(self):
        rule_map = {
            "audit-item": [
                CssRule(".audit-item", "display", "grid"),
                CssRule(".audit-item", "gap", "5px"),
            ],
            "audit-dot": [CssRule(".audit-dot", "display", "flex")],
        }
        boundary = _boundary(AUDIT_ITEM_WITH_NESTED_CLASSES_JS, name="HistoryView")
        sections = extract_sections(
            AUDIT_ITEM_WITH_NESTED_CLASSES_JS, _screen("HistoryView"), boundary,
            rule_map=rule_map,
        )
        section = next(s for s in sections if "audit" in s.name.lower())

        by_element: dict[str, set[tuple[str, str]]] = {}
        for entry in section.element_styles:
            by_element.setdefault(entry.element, set()).add((entry.property, entry.value))

        assert ("display", "grid") in by_element["class:audit-item"]
        assert ("gap", "5px") in by_element["class:audit-item"]
        assert by_element["class:audit-dot"] == {("display", "flex")}

    def test_no_rule_map_yields_no_element_styles(self):
        boundary = _boundary(AUDIT_ITEM_WITH_NESTED_CLASSES_JS, name="HistoryView")
        sections = extract_sections(
            AUDIT_ITEM_WITH_NESTED_CLASSES_JS, _screen("HistoryView"), boundary,
        )
        section = next(s for s in sections if "audit" in s.name.lower())
        assert section.element_styles == []
