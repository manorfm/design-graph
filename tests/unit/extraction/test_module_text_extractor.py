"""
Tests for module_text_extractor — UI copy embedded in module-level
constant arrays (const DETAIL_TABS = [{ key, label, desc }, ...]) that no
other extractor ever visits: component/section extraction only scans
inside function boundaries, and a shared config array like this sits
outside all of them by construction.
"""

from __future__ import annotations

from design_graph.core.models import TextType
from design_graph.extraction.module_text_extractor import extract_module_level_texts
from design_graph.parsing.js_parser import find_all_boundaries

DETAIL_TABS_JS = """
const DETAIL_TABS = [
  { key: 'overview', label: 'Visão Geral', icon: Icon.card,
    desc: 'Dados cadastrais, integrações de marketplace e modelo de pagamento desta unidade.' },
  { key: 'menus', label: 'Cardápio & Preço', icon: Icon.creditcard,
    desc: 'Publica itens no cardápio desta unidade.' },
  { key: 'sectors', label: 'Produção & Setores', icon: Icon.sectors,
    desc: 'Crie os setores de produção desta unidade.' },
];

function RestaurantDetail() {
  return (<K.Tabs items={DETAIL_TABS} active={tab} onChange={setTab} />);
}
"""


class TestExtractModuleLevelTexts:
    def _texts(self, js: str):
        bounds = find_all_boundaries(js)
        return extract_module_level_texts(js, bounds)

    def test_finds_label_from_every_element(self):
        contents = {t.content for t in self._texts(DETAIL_TABS_JS)}
        assert "Visão Geral" in contents
        assert "Cardápio & Preço" in contents
        assert "Produção & Setores" in contents

    def test_finds_description_from_every_element(self):
        contents = {t.content for t in self._texts(DETAIL_TABS_JS)}
        assert "Publica itens no cardápio desta unidade." in contents

    def test_label_classified_as_label_type(self):
        texts = self._texts(DETAIL_TABS_JS)
        label = next(t for t in texts if t.content == "Cardápio & Preço")
        assert label.text_type == TextType.LABEL

    def test_desc_classified_as_description_type(self):
        texts = self._texts(DETAIL_TABS_JS)
        desc = next(t for t in texts if t.content == "Publica itens no cardápio desta unidade.")
        assert desc.text_type == TextType.DESCRIPTION

    def test_source_is_the_constant_name(self):
        texts = self._texts(DETAIL_TABS_JS)
        assert all(t.source == "DETAIL_TABS" for t in texts)

    def test_key_field_not_extracted_as_text(self):
        # 'overview'/'menus'/'sectors' are identifiers, not copy — also
        # excluded by TextEntry.is_plausible_content's lowercase-token guard.
        contents = {t.content for t in self._texts(DETAIL_TABS_JS)}
        assert "overview" not in contents
        assert "menus" not in contents
        assert "sectors" not in contents

    def test_bare_expression_value_not_extracted_as_text(self):
        contents = {t.content for t in self._texts(DETAIL_TABS_JS)}
        assert not any("Icon" in c for c in contents)

    def test_constant_declared_inside_a_function_is_ignored(self):
        # Already covered by RE_UI_STRING's per-component sweep — indexing
        # it again here under a different source would just be a duplicate.
        js = """
        function ItemsPageV6() {
            const LOCAL_TABS = [{ key: 'a', label: 'Should not double-index' }];
            return (<div>{LOCAL_TABS.map(t => <span key={t.key}>{t.label}</span>)}</div>);
        }
        """
        texts = self._texts(js)
        assert not any(t.content == "Should not double-index" for t in texts)

    def test_lowercase_camel_case_constant_name_is_not_matched(self):
        # Screaming-case naming is the signal this is a shared copy
        # catalog, not incidental local array state.
        js = "const detailTabs = [{ key: 'a', label: 'Not a real catalog constant' }];"
        texts = self._texts(js)
        assert not any(t.content == "Not a real catalog constant" for t in texts)

    def test_empty_array_yields_no_texts(self):
        js = "const EMPTY_TABS = [];"
        assert self._texts(js) == []

    def test_array_of_non_object_elements_does_not_crash(self):
        js = "const PLAIN_LIST = ['a', 'b', 'c'];"
        assert self._texts(js) == []

    def test_no_module_constants_returns_empty_list(self):
        js = "function Btn() { return <button>OK</button>; }"
        assert self._texts(js) == []

    def test_short_or_identifier_shaped_values_are_filtered(self):
        # 'Ok' is too short (TextEntry.is_plausible_content) to be real copy.
        js = "const SHORT_LABELS = [{ key: 'a', label: 'Ok' }];"
        assert self._texts(js) == []


ROLE_META_JS = """
const ROLE_META = {
  root:  { bg: "var(--accent-soft)", color: "var(--accent)", label: "Root"  },
  admin: { bg: "var(--warn-soft)",   color: "var(--warn)",   label: "Admin" },
};

function RoleBadge({ role }) {
  const meta = ROLE_META[role];
  return <span style={{ background: meta.bg }}>{meta.label}</span>;
}
"""


class TestExtractModuleLevelTextsFromPlainObjects:
    """
    The same shared-config convention DETAIL_TABS-style arrays cover, just
    keyed by an identifier (a role, a status) instead of positioned in a
    list — `const ROLE_META = { root: { label: 'Root', ... }, ... }`. Real
    example confirmed in the `toToggle` reference prototype (docs/changes/C39).
    """

    def _texts(self, js: str):
        bounds = find_all_boundaries(js)
        return extract_module_level_texts(js, bounds)

    def test_finds_label_nested_one_level_deep(self):
        contents = {t.content for t in self._texts(ROLE_META_JS)}
        assert "Root" in contents
        assert "Admin" in contents

    def test_label_classified_as_label_type(self):
        texts = self._texts(ROLE_META_JS)
        root = next(t for t in texts if t.content == "Root")
        assert root.text_type == TextType.LABEL

    def test_source_is_the_constant_name(self):
        texts = self._texts(ROLE_META_JS)
        assert all(t.source == "ROLE_META" for t in texts)

    def test_role_key_itself_not_extracted_as_text(self):
        # 'root'/'admin' are identifiers (unquoted object keys), never
        # candidate string literals to begin with.
        contents = {t.content for t in self._texts(ROLE_META_JS)}
        assert "root" not in contents
        assert "admin" not in contents

    def test_flat_object_without_nesting_is_also_covered(self):
        js = 'const STATUS_LABELS = { active: "Active", disabled: "Disabled account" };'
        texts = self._texts(js)
        contents = {t.content for t in texts}
        assert "Active" in contents
        assert "Disabled account" in contents
        assert all(t.source == "STATUS_LABELS" for t in texts)

    def test_empty_object_yields_no_texts(self):
        js = "const EMPTY_META = {};"
        assert self._texts(js) == []
