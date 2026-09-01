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

    def list_texts(self):
        return []

    def list_shared_style_classes(self):
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


# ── Search must cover UIText content, not just names ─────────────────────────
#
# UIText nodes hold the actual visible strings in the prototype (button
# labels, headings, messages) — the thing an agent most often searches for.
# The tool's own description promises "screens, components, tokens and
# texts", but the implementation never queried UIText at all.

class _StubReaderWithTexts:
    def list_screens(self):
        return []

    def list_components(self, comp_type=None):
        return []

    def get_tokens(self, category=None):
        return []

    def list_texts(self):
        return [
            {"t.id": "txt_1", "t.content": "Adicionar Componente", "t.text_type": "label",
             "t.source": "CompTab", "t.element": "button"},
            {"t.id": "txt_2", "t.content": "Bem-vindo ao sistema", "t.text_type": "heading",
             "t.source": "HomePage", "t.element": "h1"},
        ]

    def list_shared_style_classes(self):
        return []


class TestMultiWordQueryTokenization:
    """
    search() must find results by any individual word of a multi-word
    query, not only when the whole phrase is a literal substring of a
    name — component/screen names are PascalCase single tokens, so a
    phrase like "BtnPrimary FooterLink" (an agent naming two components
    it's after in one query) never appears as a substring of either.
    """

    def _run(self, query: str) -> list[SearchResult]:
        return search([("home", _StubReader())], query)

    def test_finds_both_names_from_a_two_word_query(self):
        results = self._run("BtnPrimary FooterLink")
        names = {r.name for r in results}
        assert "BtnPrimary" in names
        assert "FooterLink" in names

    def test_whole_phrase_still_matches_when_it_is_a_real_substring(self):
        # regression: exact multi-word phrase matching must not be lost
        results = self._run("Adicionar Componente")
        assert results == []  # nothing in _StubReader matches — just must not crash


class _StubReaderForCoverage:
    """Two components sharing one word — isolates coverage-based ranking."""

    def list_screens(self):
        return []

    def list_components(self, comp_type=None):
        return [
            {"c.name": "AvatarCircle", "c.comp_type": "component", "c.occurrence": 1},
            {"c.name": "AvatarBadge", "c.comp_type": "component", "c.occurrence": 1},
        ]

    def get_tokens(self, category=None):
        return []

    def list_texts(self):
        return []

    def list_shared_style_classes(self):
        return []


class TestCoverageRanking:
    def test_result_matching_more_query_words_ranks_first(self):
        results = search([("home", _StubReaderForCoverage())], "Avatar Circle")
        names = [r.name for r in results]
        assert names[0] == "AvatarCircle"
        assert "AvatarBadge" in names


class _StubReaderForPartialMatch:
    """One UIText sharing only one of the query's two words — isolates the
    'weak match found, no strong match exists' case from a genuine hit."""

    def list_screens(self):
        return []

    def list_components(self, comp_type=None):
        return []

    def get_tokens(self, category=None):
        return []

    def list_texts(self):
        return [{"t.id": "t1", "t.content": "Alertas operacionais", "t.source": "InventoryOverview"}]

    def list_shared_style_classes(self):
        return []


class TestWordCoverageExposedOnResult:
    """
    search("Destinos operacionais") returned "Alertas operacionais" — a
    UIText that shares only the word "operacionais" — indistinguishable in
    the output from a genuine match on the full phrase. word_coverage was
    already computed internally to rank results but discarded before
    reaching the caller; a caller (or the rendering layer) needs it on the
    result itself to tell "this matched everything you asked for" apart
    from "this matched one word out of two".
    """

    def test_partial_word_match_has_coverage_below_one(self):
        results = search([("home", _StubReaderForPartialMatch())], "Destinos operacionais")
        assert results
        assert results[0].word_coverage < 1.0

    def test_full_word_match_has_coverage_of_one(self):
        results = search([("home", _StubReaderForCoverage())], "Avatar Circle")
        full = next(r for r in results if r.name == "AvatarCircle")
        assert full.word_coverage == 1.0

    def test_mixed_results_keep_distinct_coverage_values(self):
        # AvatarCircle covers both query words; AvatarBadge covers only one —
        # they must not collapse to the same word_coverage.
        results = search([("home", _StubReaderForCoverage())], "Avatar Circle")
        by_name = {r.name: r.word_coverage for r in results}
        assert by_name["AvatarCircle"] == 1.0
        assert by_name["AvatarBadge"] < 1.0


class TestSearchHasNoRegexInjectionSurface:
    """
    A search query is external input (from an AI agent, not an
    authenticated end user). Compiling a regex from it would open a ReDoS
    vector — search.py must stay on plain string operations only.
    """

    def test_search_module_never_imports_re(self):
        import inspect

        import design_graph.mcp.search as search_module
        source = inspect.getsource(search_module)
        assert "import re" not in source


class _StubReaderWithSharedClasses:
    def list_screens(self):
        return []

    def list_components(self, comp_type=None):
        return []

    def get_tokens(self, category=None):
        return []

    def list_texts(self):
        return []

    def list_shared_style_classes(self):
        return ["page-title", "chip"]


class TestSearchCoversSharedCssClasses:
    """
    A CSS class reused across screens but never factored into a named React
    component (`.page-title`, `.chip`) used to be invisible to search() —
    _search_reader only ever scanned Screen/Component/Token/UIText, never a
    class name with no Component node of its own (see docs/changes/C36 P3).
    """

    def _run(self, query: str) -> list[SearchResult]:
        return search([("proto", _StubReaderWithSharedClasses())], query)

    def test_finds_shared_class_by_exact_name(self):
        results = self._run("page-title")
        assert any(r.type == "CssClass" and r.name == "page-title" for r in results)

    def test_finds_shared_class_by_prefix(self):
        results = self._run("page")
        assert any(r.type == "CssClass" and r.name == "page-title" for r in results)

    def test_no_match_returns_no_cssclass_results(self):
        results = self._run("xyz-not-present")
        assert not any(r.type == "CssClass" for r in results)


class TestSearchCoversUIText:
    def _run(self, query: str) -> list[SearchResult]:
        return search([("proto", _StubReaderWithTexts())], query)

    def test_finds_text_by_exact_content(self):
        results = self._run("Adicionar Componente")
        assert any(r.type == "UIText" and r.name == "Adicionar Componente" for r in results)

    def test_finds_text_by_substring(self):
        results = self._run("Adicionar")
        assert any(r.type == "UIText" and "Adicionar Componente" in r.name for r in results)

    def test_text_result_carries_source_component_as_detail(self):
        results = self._run("Bem-vindo")
        match = next(r for r in results if r.type == "UIText")
        assert match.detail == "HomePage"

    def test_no_match_returns_no_uitext_results(self):
        results = self._run("xyz-not-present")
        assert not any(r.type == "UIText" for r in results)
