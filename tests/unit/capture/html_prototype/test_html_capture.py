"""html_prototype capture: how a React prototype's JS becomes screens, components and sections."""

from __future__ import annotations

import asyncio


# ── extract_react: screen/component split ─────────────────────────────────────
#
# A screen boundary must never also be extracted as a component.

class TestExtractReactResolvesPaletteReferences:
    """
    End-to-end proof that the pieces wired in html_prototype.extract_react —
    palette_extractor.discover_prototype_palette, token_extractor's
    palette-derived labels, component_extractor's reference folding —
    actually connect: a style value written as `C.bg` and its Token both
    come out pointing at the same literal hex, so writer.py's existing
    exact-value USES_TOKEN match links them without any change there.
    """

    def test_component_style_and_token_agree_on_the_resolved_hex(self):
        from design_graph.capture.html_prototype.sources import RawSources, SourceFormat
        from design_graph.capture.html_prototype.html_capture import extract_react

        js = """
        const C = {
          bg: '#404040', card: '#2a2a2a', card2: '#333333', border: '#3a3a3a',
          accent: '#FFB81C', muted: '#9ca3af',
        };
        function PricingPageV6() {
            return (<div style={{ background: C.bg, borderColor: '#404040' }} />);
        }
        """
        sources = RawSources(js=js, css="", inner_html="", html_hash="x", format=SourceFormat.BUNDLED_REACT)
        result = asyncio.run(extract_react(sources, concurrency=1))

        pricing = next(c for c in result.components if c.name == "PricingPageV6")
        background = next(s for s in pricing.styles if s.property == "background")
        assert background.value == "#404040"

        bg_token = next(t for t in result.tokens if t.value == "#404040")
        assert bg_token.label == "bg"


class TestExtractReactScreenComponentSplit:
    def test_screen_boundary_excluded_from_extracted_components(self):
        from design_graph.capture.html_prototype.sources import RawSources, SourceFormat
        from design_graph.capture.html_prototype.html_capture import extract_react

        js = """
        function BtnPrimary() { return <button>Click</button>; }
        function HomePage() {
          return (<div><BtnPrimary /></div>);
        }
        """
        sources = RawSources(js=js, css="", inner_html="", html_hash="x", format=SourceFormat.BUNDLED_REACT)
        result = asyncio.run(extract_react(sources, concurrency=1))
        assert "HomePage" not in [c.name for c in result.components]
        assert "BtnPrimary" in [c.name for c in result.components]
        assert "HomePage" in [s.name for s in result.screens]

    def test_overlay_shell_excluded_from_extracted_components(self):
        # C23/T43: a name that carries none of ScreenIdentity's suffixes
        # (Page/Screen/Dashboard/View/Detail) still becomes a screen — not
        # a component — when its own body conditionally switches between
        # 2+ Tab-suffixed children (a full-page multi-tab editor shell).
        from design_graph.capture.html_prototype.sources import RawSources, SourceFormat
        from design_graph.capture.html_prototype.html_capture import extract_react

        js = """
        function BasicTab() { return <div>basic</div>; }
        function CompTab() { return <div>comp</div>; }
        function ItemEditorV6({ tab }) {
          return (
            <div>
              {tab === 'basic' && <BasicTab />}
              {tab === 'comp' && <CompTab />}
            </div>
          );
        }
        """
        sources = RawSources(js=js, css="", inner_html="", html_hash="x", format=SourceFormat.BUNDLED_REACT)
        result = asyncio.run(extract_react(sources, concurrency=1))
        assert "ItemEditorV6" not in [c.name for c in result.components]
        assert "BasicTab" in [c.name for c in result.components]
        assert "ItemEditorV6" in [s.name for s in result.screens]
        editor = next(s for s in result.screens if s.name == "ItemEditorV6")
        assert "BasicTab" in editor.component_refs
        assert "CompTab" in editor.component_refs


class TestExtractReactSectionsResolveCssClasses:
    """
    HistoryView-style screens style their sections' containers via CSS
    classes, never inline style={{}} — extract_react must forward the
    stylesheet's rule_map into extract_sections so a Section built from a
    raw-markup `.map()` row (section_extractor's inline-list fallback)
    carries real resolved styles, not just structure. Class-resolved styles
    live in element_styles (attributed per selector), not the flat `styles`
    dict — see docs/changes/C36.
    """

    def test_list_item_section_carries_css_class_resolved_style(self):
        from design_graph.capture.html_prototype.sources import RawSources, SourceFormat
        from design_graph.capture.html_prototype.html_capture import extract_react

        js = """
        function HistoryView() {
            return (
                <div className="audit">
                    {items.map((e, i) => (
                        <div className="audit-item" key={e.id}>
                            <Icon name="history" size={15} />
                        </div>
                    ))}
                </div>
            )
        }
        """
        css = ".audit-item { display: flex; padding: 12px; }"
        sources = RawSources(js=js, css=css, inner_html="", html_hash="x", format=SourceFormat.BUNDLED_REACT)
        result = asyncio.run(extract_react(sources, concurrency=1))
        history_sections = result.sections["HistoryView"]
        audit_item = next(s for s in history_sections if "Icon" in s.component_refs)
        resolved = {(e.property, e.value) for e in audit_item.element_styles if e.element == "class:audit-item"}
        assert ("display", "flex") in resolved
        assert ("padding", "12px") in resolved


# ── extract_react: component alias resolution ──────────────────────────────
#
# Some prototypes rename a component and keep the old name as a plain
# re-export (`const Badge = window.V6K.Pill;`) instead of a function. Left
# alone, that produces an empty unresolved-component shell for the alias
# name. extract_react must resolve it to the real definition everywhere the
# alias is referenced — by other components and by screens alike.

class TestExtractReactComponentAliasResolution:
    _JS = """
    function Pill({ label, color }) {
      return <span style={{color}}>{label}</span>;
    }
    const Badge = window.V6K.Pill;
    function RestaurantRow({ r }) {
      return (<div><Badge label={r.status} /></div>);
    }
    function RestaurantsPage() {
      return (
        <div>
          {/* ── Lista ── */}
          <RestaurantRow r={r} />
          <Badge label="top" />
        </div>
      );
    }
    """

    def _extract(self):
        from design_graph.capture.html_prototype.sources import RawSources, SourceFormat
        from design_graph.capture.html_prototype.html_capture import extract_react

        sources = RawSources(js=self._JS, css="", inner_html="", html_hash="x", format=SourceFormat.BUNDLED_REACT)
        return asyncio.run(extract_react(sources, concurrency=1))

    def test_alias_name_is_not_extracted_as_its_own_component(self):
        result = self._extract()
        assert "Badge" not in [c.name for c in result.components]
        assert "Pill" in [c.name for c in result.components]

    def test_component_child_refs_resolve_alias_to_target(self):
        result = self._extract()
        row = next(c for c in result.components if c.name == "RestaurantRow")
        assert "Badge" not in row.child_refs
        assert "Pill" in row.child_refs

    def test_screen_component_refs_resolve_alias_to_target(self):
        result = self._extract()
        page = next(s for s in result.screens if s.name == "RestaurantsPage")
        assert "Badge" not in page.component_refs
        assert "Pill" in page.component_refs
        # RestaurantRow already referenced Pill via the alias — the direct
        # <Badge label="top" /> reference must dedupe into the same entry.
        assert page.component_refs.count("Pill") == 1

    def test_section_component_refs_resolve_alias_to_target(self):
        # Sections are collected independently of screens/components — the
        # writer creates unresolved shells straight from section.component_refs
        # (graph/writer.py write_screen), so this leak survives even after
        # screen- and component-level refs are fixed unless handled here too.
        result = self._extract()
        sections = result.sections["RestaurantsPage"]
        section = next(s for s in sections if s.name == "Lista")
        assert "Badge" not in section.component_refs
        assert "Pill" in section.component_refs


class TestSourceDescription:
    """
    The capture — not the interfaces — states what language each stored
    source is written in, whether it simplified the original while storing
    it, and whether the source declares inline styling.
    """

    _JS = """
    function Badge({ label }) {
      return <span style={{ color: '#ff0000' }}>{label}</span>;
    }
    function Plain() {
      return <p>static text here</p>;
    }
    function CartList({ items }) {
      return (<ul>{items.map(item => <Badge label={item.name} />)}</ul>);
    }
    function HomePage() {
      return (
        <div>
          {/* ── Header ── */}
          <div style={{ padding: '16px' }}><Badge label="x" /></div>
        </div>
      );
    }
    """

    def _result(self):
        from design_graph.capture.html_prototype.html_capture import extract_react
        from design_graph.capture.html_prototype.sources import RawSources, SourceFormat

        sources = RawSources(js=self._JS, css="", inner_html="", html_hash="x", format=SourceFormat.BUNDLED_REACT)
        return asyncio.run(extract_react(sources, concurrency=1))

    def _component(self, name):
        return next(c for c in self._result().components if c.name == name)

    def test_react_sources_are_jsx(self):
        result = self._result()
        assert {c.source_lang for c in result.components} == {"jsx"}
        assert {s.source_lang for s in result.screens} == {"jsx"}
        assert {sec.source_lang for secs in result.sections.values() for sec in secs} == {"jsx"}

    def test_collapsed_list_render_marks_source_simplified(self):
        assert self._component("CartList").source_simplified is True

    def test_untouched_source_is_not_simplified(self):
        assert self._component("Plain").source_simplified is False

    def test_inline_style_object_is_declared(self):
        assert self._component("Badge").declares_inline_styles is True
        assert self._component("Plain").declares_inline_styles is False

    def test_plain_html_sources_are_html(self):
        from design_graph.capture.base import PrototypeDocument
        from design_graph.capture.registry import capture_for
        from pathlib import Path

        document = PrototypeDocument.read(Path(__file__).parents[3] / "fixtures" / "plain.html")
        result = asyncio.run(capture_for(document).capture(document, concurrency=1))
        assert {c.source_lang for c in result.components} == {"html"}
        assert {sec.source_lang for secs in result.sections.values() for sec in secs} <= {"html"}

    def test_inline_styling_inside_an_icon_counts_as_declared(self):
        from design_graph.capture.html_prototype.html_capture import extract_react
        from design_graph.capture.html_prototype.sources import RawSources, SourceFormat

        js = "function Glyph() { return <svg style={{ width: size }}><path d='M0 0'/></svg>; }"
        sources = RawSources(js=js, css="", inner_html="", html_hash="x", format=SourceFormat.BUNDLED_REACT)
        glyph = next(c for c in asyncio.run(extract_react(sources, concurrency=1)).components if c.name == "Glyph")
        assert "{[icon:" in glyph.source_code
        assert glyph.declares_inline_styles is True
