"""Tests for js_parser — T03."""

import pytest

from design_graph.core.patterns import RE_COMP_ARROW_FN, RE_COMP_FN
from design_graph.extraction.visual_function import VisualFunctionCandidate
from design_graph.parsing.js_parser import (
    extract_return_block,
    find_all_boundaries,
    find_function_boundaries,
    find_function_end,
    is_quoted_string_literal,
    iter_object_literal_pairs,
    iter_style_object_blocks,
    parse_object_literal_props,
    split_top_level,
    unwrap_quoted_literal,
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


class TestArrowFunctionComponents:
    """
    const Name = ({ ... }) => ( <jsx/> ) declarations were previously invisible
    to boundary detection (RE_COMP_FN only matches `function Name(`), so a
    component defined this way became a graph node with no jsx_snippet,
    styles, props or interactions — reported by `design-graph validate` as
    "unresolved". Reproduces the OptRow pattern from a real prototype.
    """

    def test_finds_implicit_return_arrow_component(self):
        js = "const OptRow = ({ o, on }) => (\n  <div>{o.label}</div>\n);"

        bounds = find_all_boundaries(js)
        names = {b.name for b in bounds}

        assert "OptRow" in names

    def test_extracts_jsx_from_implicit_return_arrow_component(self):
        js = "const OptRow = ({ o, on }) => (\n  <div>{o.label}</div>\n);"

        boundary = find_all_boundaries(js)[0]
        jsx = extract_return_block(js, boundary.start, boundary.end)

        assert "<div>{o.label}</div>" in jsx
        assert "OptRow" not in jsx  # declaration prefix excluded from the JSX

    def test_arrow_component_recognized_as_visual(self):
        js = "const OptRow = ({ o, on }) => (\n  <div>{o.label}</div>\n);"

        boundary = find_all_boundaries(js)[0]

        assert VisualFunctionCandidate.from_source(js, boundary).renders_visual_output

    def test_finds_brace_bodied_arrow_component(self):
        js = "const Badge = ({ label }) => { return (<span>{label}</span>); };"

        boundary = find_all_boundaries(js)[0]
        jsx = extract_return_block(js, boundary.start, boundary.end)

        assert boundary.name == "Badge"
        assert "<span>{label}</span>" in jsx

    def test_arrow_component_style_object_not_mistaken_for_body_end(self):
        js = (
            "const OptRow = ({ on, color }) => (\n"
            "  <div style={{ background: on ? color : '#2a2a2a' }}>x</div>\n"
            ");\n"
            "function After() { return <b/>; }"
        )

        bounds = find_all_boundaries(js)
        names = {b.name for b in bounds}

        assert {"OptRow", "After"}.issubset(names)

    def test_nested_arrow_component_does_not_truncate_parent(self):
        """A component defined inside another component's body (OptRow's real
        shape) must get its own boundary without corrupting the parent's."""
        js = """
        function ClientItemDetail() {
            const OptRow = ({ o }) => (
                <div>{o.label}</div>
            );
            return (
                <main>
                    <OptRow o={item} />
                    <FooterBar />
                </main>
            );
        }
        """

        bounds = {b.name: b for b in find_all_boundaries(js)}

        assert "OptRow" in bounds
        assert "ClientItemDetail" in bounds
        parent = bounds["ClientItemDetail"]
        assert "FooterBar" in js[parent.start:parent.end]
        assert "<OptRow" in js[parent.start:parent.end]
        child = bounds["OptRow"]
        assert parent.start < child.start < child.end <= parent.end

    def test_non_component_arrow_const_not_matched(self):
        js = "const D = () => window.V6; function Card() { return <div/>; }"

        names = {b.name for b in find_all_boundaries(js)}

        assert "D" not in names
        assert "Card" in names

    def test_find_function_boundaries_still_strict_sibling_non_overlap(self):
        js = "const A = (p) => (<div/>); const B = (p) => (<span/>);"

        bounds = sorted(
            find_function_boundaries(js, RE_COMP_ARROW_FN), key=lambda b: b.start
        )

        for i in range(len(bounds) - 1):
            assert bounds[i].end <= bounds[i + 1].start


class TestVersionedComponentNames:
    """
    Real prototypes commonly version component/screen names with a trailing
    digit (ItemCardV6, KDSPageV7) — [a-zA-Z] name-body classes silently
    excluded these entirely (not extracted, not resolved as screens, not
    recognized as JSX child references).
    """

    def test_function_component_with_trailing_digit_found(self):
        js = "function ItemCardV6({ item }) { return <div>{item.name}</div>; }"
        names = {b.name for b in find_all_boundaries(js)}
        assert "ItemCardV6" in names

    def test_arrow_component_with_trailing_digit_found(self):
        js = "const ItemCardV6 = ({ item }) => (<div>{item.name}</div>);"
        names = {b.name for b in find_all_boundaries(js)}
        assert "ItemCardV6" in names

    def test_screen_function_with_trailing_digit_found(self):
        js = "function ItemsPageV6() { return (<div><h1>Items</h1></div>); }"
        names = {b.name for b in find_all_boundaries(js)}
        assert "ItemsPageV6" in names

    def test_digit_in_middle_of_name_found(self):
        js = "function Step2Form() { return <form/>; }"
        names = {b.name for b in find_all_boundaries(js)}
        assert "Step2Form" in names


class TestIterStyleObjectBlocks:
    """
    A `[^}]`-style regex over `style={{ ... }}` truncates at the first `}`
    it meets — including one belonging to a `${expr}` interpolation nested
    inside a template-literal value, not the object's real closing `}}`.
    Real prototypes routinely write `border: \\`1px solid ${cond ? a : b}\\``
    inside a style block; the block must still resolve to its true end.
    """

    def test_simple_block_found(self):
        js = "<div style={{ color: 'red', padding: 8 }} />"
        blocks = list(iter_style_object_blocks(js))
        assert blocks == [" color: 'red', padding: 8 "]

    def test_template_literal_interpolation_does_not_truncate_block(self):
        js = "<button style={{ background: '#2e2e2e', border: `1.5px solid ${C.border2}` }} />"
        blocks = list(iter_style_object_blocks(js))
        assert len(blocks) == 1
        assert "border" in blocks[0]
        assert blocks[0].strip().endswith("`1.5px solid ${C.border2}`")

    def test_two_blocks_in_same_component_both_found(self):
        js = (
            "<button style={{ background: on ? color : '#2e2e2e' }}>"
            "<span style={{ width: 7, height: 7 }} />"
            "</button>"
        )
        blocks = list(iter_style_object_blocks(js))
        assert len(blocks) == 2
        assert "background" in blocks[0]
        assert "width" in blocks[1]

    def test_no_style_attribute_yields_nothing(self):
        js = "<div className='card'>text</div>"
        assert list(iter_style_object_blocks(js)) == []


class TestParseObjectLiteralProps:
    """
    RE_STYLE_PROP's value char class excluded quotes, so a ternary with
    quoted branches (`cursor: disabled ? 'not-allowed' : 'pointer'`) was
    captured only up to its condition (`disabled ?`) — the actual branch
    values, the part an agent needs to reconstruct the selected/unselected
    look, never made it into the graph.
    """

    def test_simple_quoted_value_unwrapped(self):
        props = parse_object_literal_props(" color: 'red', padding: 8 ")
        assert ("color", "red") in props
        assert ("padding", "8") in props

    def test_ternary_with_quoted_branches_kept_whole(self):
        block = "background: on ? color + '1e' : '#2e2e2e', border: '1px solid gray'"
        props = dict(parse_object_literal_props(block))
        assert props["background"] == "on ? color + '1e' : '#2e2e2e'"
        assert props["border"] == "1px solid gray"

    def test_condition_with_comparison_and_quoted_branches_kept_whole(self):
        block = "background: value === o.value ? '#444' : 'transparent'"
        props = dict(parse_object_literal_props(block))
        assert props["background"] == "value === o.value ? '#444' : 'transparent'"

    def test_template_literal_value_kept_whole(self):
        block = "border: `1.5px solid ${C.border2}`"
        props = dict(parse_object_literal_props(block))
        assert props["border"] == "`1.5px solid ${C.border2}`"

    def test_comma_inside_template_literal_does_not_split_pair(self):
        block = "boxShadow: `0 0 0 1px ${C.accent}22, 0 4px 20px #0005`, opacity: 1"
        props = dict(parse_object_literal_props(block))
        assert props["boxShadow"] == "`0 0 0 1px ${C.accent}22, 0 4px 20px #0005`"
        assert props["opacity"] == "1"

    def test_entry_without_colon_is_skipped(self):
        # A `...spread` entry inside the same block has no `key:` — must not
        # be mistaken for a prop with an empty value.
        props = parse_object_literal_props("...base, color: 'red'")
        assert props == [("color", "red")]


class TestIsQuotedStringLiteral:
    def test_single_quoted_is_literal(self):
        assert is_quoted_string_literal("'Cardápio & Preço'") is True

    def test_double_quoted_is_literal(self):
        assert is_quoted_string_literal('"Produção & Setores"') is True

    def test_bare_member_expression_is_not_literal(self):
        assert is_quoted_string_literal("Icon.card") is False

    def test_bare_identifier_is_not_literal(self):
        assert is_quoted_string_literal("overview") is False

    def test_template_literal_is_not_a_plain_string_literal(self):
        # Backtick strings can embed ${expr} — not safe to treat as static text.
        assert is_quoted_string_literal("`1px solid ${C.border2}`") is False

    def test_mismatched_quotes_not_literal(self):
        assert is_quoted_string_literal("'oops\"") is False


class TestUnwrapQuotedLiteral:
    def test_strips_matching_single_quotes(self):
        assert unwrap_quoted_literal("'red'") == "red"

    def test_leaves_unquoted_value_untouched(self):
        assert unwrap_quoted_literal("Icon.card") == "Icon.card"


class TestSplitTopLevel:
    """
    The general depth-aware splitter both parse_object_literal_props (key:
    value pairs) and module-level constant-array extraction (array
    elements) build on — one comma-splitting primitive instead of two
    independent reimplementations that could drift apart.
    """

    def test_splits_on_top_level_commas(self):
        assert split_top_level("a, b, c") == ["a", " b", " c"]

    def test_comma_inside_nested_braces_does_not_split(self):
        parts = split_top_level("{ a: 1, b: 2 }, { c: 3 }")
        assert len(parts) == 2

    def test_comma_inside_quotes_does_not_split(self):
        parts = split_top_level("label: 'a, b', next: 1")
        assert len(parts) == 2

    def test_custom_separator(self):
        assert split_top_level("a:b:c", separator=":") == ["a", "b", "c"]


class TestIterObjectLiteralPairs:
    def test_values_kept_raw_not_unwrapped(self):
        pairs = list(iter_object_literal_pairs("label: 'Cardápio & Preço', icon: Icon.card"))
        assert ("label", "'Cardápio & Preço'") in pairs
        assert ("icon", "Icon.card") in pairs
