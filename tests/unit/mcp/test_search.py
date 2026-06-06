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
