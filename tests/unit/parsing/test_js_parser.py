"""Tests for js_parser — T03."""

import pytest

from design_graph.core.patterns import RE_COMP_FN, RE_SCREEN_FN
from design_graph.parsing.js_parser import (
    extract_return_block,
    find_all_boundaries,
    find_function_boundaries,
    find_function_end,
)


class TestFindFunctionEnd:
    def test_simple_function_ends_at_closing_brace(self):
        js = "function Foo() { return 1; } rest_of_file"
        end = find_function_end(js, 0)
        assert js[end - 1] == "}"
        assert "rest_of_file" in js[end:]

    def test_nested_object_literal_not_premature_close(self):
        js = "function Foo() { const x = {a: {b: 1}}; return x; } after"
        end = find_function_end(js, 0)
        assert "after" in js[end:]

    def test_inline_style_double_braces_handled(self):
        js = "function Btn() { return (<div style={{color:'red'}} />); } next"
        end = find_function_end(js, 0)
        assert "next" in js[end:]

    def test_deeply_nested_braces_resolved(self):
        js = "function Deep() { if (a) { if (b) { if (c) { return 1; } } } } end"
        end = find_function_end(js, 0)
        assert "end" in js[end:]

    def test_result_never_before_start(self):
        js = "function A() {} function B() {}"
        end = find_function_end(js, 0)
        assert end > 0

    def test_truncated_function_uses_fallback(self):
        js = "function Broken() { " + "x" * 200_000
        end = find_function_end(js, 0)
        assert end <= len(js)  # does not crash

    def test_start_with_no_brace_uses_fallback(self):
        # No "{" found at all — should return a safe fallback
        js = "function Foo() no_body_here"
        end = find_function_end(js, 0)
        assert end > 0
        assert end <= len(js)

    def test_sibling_functions_do_not_overlap(self):
        js = """
        function CompA() { return (<div><Badge /></div>); }
        function CompB() { return (<div><Icon /></div>); }
        """
        end_a = find_function_end(js, js.index("function CompA"))
        start_b = js.index("function CompB")
        assert end_a <= start_b


class TestExtractReturnBlock:
    def test_extracts_simple_jsx(self):
        js = "function Foo() { return (<div>hello</div>); }"
        result = extract_return_block(js, 0, len(js))
        assert "<div>hello</div>" in result

    def test_extracts_multiline_jsx(self):
        js = """function Foo() {
            return (
                <div>
                    <span>text</span>
                </div>
            );
        }"""
        result = extract_return_block(js, 0, len(js))
        assert "<span>text</span>" in result

    def test_handles_no_return_gracefully(self):
        js = "function Foo() { const x = 1; }"
        result = extract_return_block(js, 0, len(js))
        assert result == ""

    def test_nested_parens_not_closed_early(self):
        js = "function Foo() { return (fn(a, (b + c))); }"
        result = extract_return_block(js, 0, len(js))
        assert result != ""

    def test_return_without_space_also_works(self):
        js = "function Foo() { return(<div/>); }"
        result = extract_return_block(js, 0, len(js))
        assert "<div/>" in result

    def test_never_returns_none(self):
        js = "function Foo() {}"
        assert extract_return_block(js, 0, len(js)) is not None

    def test_empty_string_returns_empty(self):
        assert extract_return_block("", 0, 0) == ""


class TestFindFunctionBoundaries:
    JS = """
    function BtnPrimary() { return <div/>; }
    function SectionCard() { return <div/>; }
    function useState() { return null; }
    function NotPascalcase() { return null; }
    """

    def test_finds_pascal_case_functions(self):
        bounds = find_function_boundaries(self.JS, RE_COMP_FN)
        names = {b.name for b in bounds}
        assert "BtnPrimary" in names
        assert "SectionCard" in names

    def test_end_is_strictly_after_start(self):
        bounds = find_function_boundaries(self.JS, RE_COMP_FN)
        for b in bounds:
            assert b.end > b.start

    def test_body_start_between_start_and_end(self):
        bounds = find_function_boundaries(self.JS, RE_COMP_FN)
        for b in bounds:
            assert b.start <= b.body_start <= b.end

    def test_boundaries_do_not_overlap(self):
        bounds = sorted(
            find_function_boundaries(self.JS, RE_COMP_FN), key=lambda b: b.start
        )
        for i in range(len(bounds) - 1):
            assert bounds[i].end <= bounds[i + 1].start, (
                f"{bounds[i].name}.end={bounds[i].end} > "
                f"{bounds[i+1].name}.start={bounds[i+1].start}"
            )

    def test_screen_pattern_only_matches_screens(self):
        js = """
        function RestaurantsPage() { return <div/>; }
        function BtnPrimary() { return <div/>; }
        function LoginForm() { return <div/>; }
        """
        bounds = find_function_boundaries(js, RE_SCREEN_FN)
        names = {b.name for b in bounds}
        assert "RestaurantsPage" in names
        assert "LoginForm" in names
        assert "BtnPrimary" not in names

    def test_empty_js_returns_empty_list(self):
        assert find_function_boundaries("", RE_COMP_FN) == []

    def test_no_functions_returns_empty_list(self):
        assert find_function_boundaries("const x = 1;", RE_COMP_FN) == []


class TestFindAllBoundaries:
    def test_finds_all_pascal_case_functions(self):
        js = """
        function RestaurantsPage() { return <div/>; }
        function BtnPrimary() { return <div/>; }
        function SectionCard() { return <div/>; }
        """
        bounds = find_all_boundaries(js)
        names = {b.name for b in bounds}
        assert {"RestaurantsPage", "BtnPrimary", "SectionCard"}.issubset(names)

    def test_no_duplicates(self):
        js = "function Foo() { return 1; } function Bar() { return 2; }"
        bounds = find_all_boundaries(js)
        names = [b.name for b in bounds]
        assert len(names) == len(set(names))
