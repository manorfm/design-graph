"""Tests for mcp/search.py and mcp/aliases.py — T14."""

import pytest

from design_graph.mcp.aliases import get_aliases
from design_graph.mcp.search import SearchResult, expand_query, score_match, search


class TestScoreMatch:
    @pytest.mark.parametrize("name,query,expected", [
        ("SectionCard",           "SectionCard",    100),
        ("SECTIONCARD",           "sectioncard",    100),
        ("SectionCard",           "Section",         80),
        ("SectionCard",           "Card",            60),
        ("RestaurantSectionCard", "rant",             40),  # substring only
        ("BtnPrimary",            "Modal",            0),
        ("",                      "test",             0),
        ("BtnPrimary",            "",                 0),
    ])
    def test_score_cases(self, name, query, expected):
        assert score_match(name, query) == expected

    def test_case_insensitive_exact(self):
        assert score_match("SectionCard", "sectioncard") == 100

    def test_case_insensitive_prefix(self):
        assert score_match("SectionCard", "SECTION") == 80


class TestExpandQuery:
    def test_original_term_always_included(self):
        terms = expand_query("card", {})
        assert "card" in terms

    def test_alias_expanded_lowercase(self):
        aliases = {"botão": ["Btn", "Button"]}
        terms = expand_query("botão", aliases)
        assert "btn" in terms or "button" in terms

    def test_deduplicates_terms(self):
        aliases = {"btn": ["Btn", "Button"]}
        terms = expand_query("btn btn", aliases)
        assert terms.count("btn") == 1

    def test_capped_at_max_length(self):
        aliases = {"big": [f"Term{i}" for i in range(20)]}
        terms = expand_query("big", aliases)
        assert len(terms) <= 6

    def test_empty_query_returns_empty(self):
        assert expand_query("", {}) == []

    def test_whitespace_only_returns_empty(self):
        assert expand_query("   ", {}) == []


class TestGetAliases:
    def test_returns_dict(self):
        assert isinstance(get_aliases(), dict)

    def test_botao_key_present(self):
        aliases = get_aliases()
        assert "botão" in aliases or "botao" in aliases

    def test_returned_dict_is_isolated_copy(self):
        a = get_aliases()
        b = get_aliases()
        a["injected"] = []
        assert "injected" not in b


class TestPtAliasesCoverage:
    """Verify all required PT design-system terms are mapped."""

    def _aliases(self):
        return get_aliases()

    def test_tela_maps_to_screen_or_page(self):
        aliases = self._aliases()
        assert "tela" in aliases
        targets = aliases["tela"]
        assert any(t in targets for t in ("Screen", "Page", "screen", "page"))

    def test_tipografia_maps_to_font_or_typography(self):
        aliases = self._aliases()
        assert "tipografia" in aliases
        targets = aliases["tipografia"]
        assert any(t in targets for t in ("typography", "font", "text", "Font", "Typography"))

    def test_sombra_maps_to_shadow(self):
        aliases = self._aliases()
        assert "sombra" in aliases
        targets = aliases["sombra"]
        assert any(t in targets for t in ("shadow", "Shadow"))

    def test_raio_maps_to_radius(self):
        aliases = self._aliases()
        assert "raio" in aliases
        targets = aliases["raio"]
        assert any(t in targets for t in ("radius", "Radius"))

    def test_expand_query_resolves_tela(self):
        aliases = self._aliases()
        terms = expand_query("tela", aliases)
        assert any(t.lower() in ("screen", "page") for t in terms)

    def test_expand_query_resolves_sombra(self):
        aliases = self._aliases()
        terms = expand_query("sombra", aliases)
        assert any("shadow" in t.lower() for t in terms)


# ── Search component coverage: all components, not just top-5 ────────────────

class _StubReader:
    """
    Minimal reader stub for component search coverage tests.
    list_screens() returns exactly 5 top_components per screen.
    list_components() returns ALL 8 components.
    The 3 components beyond the top-5 must still be found by search.
    """

    _ALL_COMPS = [
        "SectionCard", "BtnPrimary", "InputText", "HeaderBar", "NavItem",  # top-5
        "FooterLink", "AvatarCircle", "BadgeCount",                          # hidden from top_components
    ]

    def list_screens(self):
        return [
            {"name": "HomePage", "component_count": 8, "sections_count": 1,
             "top_components": self._ALL_COMPS[:5]},  # only first 5
        ]

    def list_components(self, comp_type=None):
        return [{"c.name": n, "c.comp_type": "component", "c.occurrence": 1}
                for n in self._ALL_COMPS]

    def get_tokens(self, category=None):
        return []


class TestSearchCoversAllComponents:
    """search() must find every component, not only the 5 in top_components."""

    def _run(self, query: str) -> list[str]:
        return [r.name for r in search([("home", _StubReader())], query)]

    def test_top5_component_found(self):
        assert "BtnPrimary" in self._run("BtnPrimary")

    def test_6th_component_found(self):
        assert "FooterLink" in self._run("FooterLink")

    def test_7th_component_found(self):
        assert "AvatarCircle" in self._run("AvatarCircle")

    def test_8th_component_found(self):
        assert "BadgeCount" in self._run("BadgeCount")

    def test_prefix_match_on_hidden_component(self):
        results = self._run("Footer")
        assert "FooterLink" in results

    def test_all_comps_discoverable_by_name(self):
        reader  = _StubReader()
        missing = []
        for comp in reader._ALL_COMPS:
            if comp not in self._run(comp):
                missing.append(comp)
        assert missing == [], f"Components not found by search: {missing}"
