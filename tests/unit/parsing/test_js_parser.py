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

    def test_destructured_parameters_are_not_mistaken_for_function_body(self):
        js = "function RestaurantsPage({ onSelect, onNew }) { return (<main>Restaurants</main>); }"

        end = find_function_end(js, 0)

        assert js[:end].endswith("}")
        assert "Restaurants" in js[:end]

    def test_braces_inside_literals_and_comments_do_not_close_function(self):
        js = '''function Card({ value = { nested: true } }) {
            const text = "}";
            const template = `card ${value}`;
            // } is not the function end
            /* { neither is this } */
            return (<div>{text}</div>);
        } after'''

        end = find_function_end(js, 0)

        assert "return (<div>" in js[:end]
        assert js[end:].strip() == "after"


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

    def test_extracts_direct_jsx_return_without_parentheses(self):
        js = "function Input() { return <input value={value} />; }"

        result = extract_return_block(js, 0, len(js))

        assert result == "<input value={value} />"

    def test_selects_visual_return_after_nested_callback_return(self):
        js = '''function Drawer() {
            useEffect(() => { return () => cleanup(); }, []);
            return (<aside>Profile</aside>);
        }'''

        result = extract_return_block(js, 0, len(js))

        assert "<aside>Profile</aside>" in result
        assert "cleanup" not in result

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

    def test_destructured_component_boundary_contains_visual_return(self):
        js = "function DashboardPage({ plan, options = {} }) { return (<Dashboard plan={plan} />); }"

        boundary = find_all_boundaries(js)[0]

        assert js[boundary.body_start] == "{"
        assert "return (<Dashboard" in js[boundary.start:boundary.end]

    def test_ignores_function_declarations_inside_non_executable_text(self):
        js = '''
        // function CommentedPage() { return (<div>wrong</div>); }
        const source = "function StringPage() { return (<div>wrong</div>); }";
        const template = `function TemplatePage() { return (<div>wrong</div>); }`;
        /* function BlockCommentPage() { return (<div>wrong</div>); } */
        function RealPage() { return (<main>right</main>); }
        '''

        names = [boundary.name for boundary in find_all_boundaries(js)]

        assert names == ["RealPage"]
