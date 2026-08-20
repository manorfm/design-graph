"""
Tests for jsx_sanitizer.sanitize_jsx — typed-marker collapsing of dynamic
JSX expressions (.map / && / ?:) and protection of raw-markup conditionals.

Reproduces a real gap found via the design-graph MCP tools: ItemsPage's
ItemCard component (ipede_manager_v15.1 prototype) renders two badges
conditionally, each with a `color={...}` prop of its own:

    {item.promotional && <Badge label="Promo" color={C.red} />}
    {item.discount && <Badge color={C.blue} />}

The old tail regex `[^}]{0,400}\\}` stopped at the FIRST `}` it met — the
one closing `color={C.red}` — leaving the rest of the JSX (` />}`) as raw
leaked text glued right after the marker:

    {[conditional:Badge]} color={C.blue} />}

The same component also has a highlight star wrapped in raw markup
(`{item.highlight && (<span><svg>...</svg></span>)}`), which survived only
because it happened to be short — a long sibling with the same shape would
have been silently erased to a bare `{...}` by the generic long-expression
fallback. Both are fixed by scanning for the expression's true balanced end
instead of trusting a regex tail.
"""

from __future__ import annotations

from design_graph.extraction.jsx_sanitizer import sanitize_jsx


class TestConditionalWithNestedBraceProp:
    def test_prop_with_own_braces_does_not_leak_after_marker(self):
        jsx = '{item.promotional && <Badge label="Promo" color={C.red} />}'
        result = sanitize_jsx(jsx)
        assert result == "{[conditional:Badge]}"

    def test_two_conditionals_each_with_nested_brace_prop(self):
        jsx = (
            '{item.discount && <Badge color={C.blue} />}\n'
            '{item.promotional && <Badge label="Promo" />}'
        )
        result = sanitize_jsx(jsx)
        assert result == "{[conditional:Badge]}\n{[conditional:Badge]}"
        assert "color={C.blue}" not in result
        assert "/>" not in result

    def test_dynamic_label_expression_prop_does_not_leak(self):
        jsx = '{item.discount && <Badge label={`-${item.discount}%`} color={C.blue} />}'
        result = sanitize_jsx(jsx)
        assert result == "{[conditional:Badge]}"


class TestEitherWithNestedBraceProp:
    def test_then_branch_prop_with_own_braces_does_not_leak(self):
        jsx = '{ok ? <SuccessCard color={C.green} /> : <ErrorBanner />}'
        result = sanitize_jsx(jsx)
        assert result == "{[either:SuccessCard|ErrorBanner]}"

    def test_else_branch_prop_with_own_braces_does_not_leak(self):
        jsx = '{ok ? <SuccessCard /> : <ErrorBanner color={C.red} />}'
        result = sanitize_jsx(jsx)
        assert result == "{[either:SuccessCard|ErrorBanner]}"

    def test_ternary_with_null_else_branch_is_left_untouched(self):
        # No component in the else branch — not this collapser's to handle;
        # must fall through unmodified (matches the pre-existing behaviour
        # for a plain regex non-match).
        jsx = "{ok ? <SuccessCard /> : null}"
        result = sanitize_jsx(jsx)
        assert "SuccessCard" in result
        assert "[either:" not in result


class TestListWithNestedBraceProp:
    def test_map_child_prop_with_own_braces_does_not_leak(self):
        jsx = "{items.map(item => <CartItem key={item.id} style={{color: C.red}} />)}"
        result = sanitize_jsx(jsx)
        assert result == "{[list:CartItem]}"


class TestRawMarkupConditionalSurvivesRegardlessOfLength:
    def test_short_raw_markup_conditional_preserved(self):
        jsx = (
            '{item.highlight && ('
            '<span title="Em destaque" style={{ color: C.accent }}>'
            '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">'
            '<polygon points="12,2 15,8 22,9" /></svg></span>)}'
        )
        result = sanitize_jsx(jsx)
        assert "<svg" in result
        assert "<polygon" in result
        assert "{...}" not in result

    def test_long_raw_markup_conditional_preserved_not_erased(self):
        # Same shape as the short case above but padded well past the
        # generic long-expression fallback's 300-char threshold. Before the
        # fix, survival was pure luck of character count; a block this size
        # was silently erased to a bare "{...}" with zero information left.
        padding = " ".join(f'data-decoy-{i}="{i}"' for i in range(40))
        jsx = (
            "{item.highlight && ("
            f'<span title="Em destaque" {padding}>'
            '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">'
            '<polygon points="12,2 15,8 22,9" /></svg></span>)}'
        )
        assert len(jsx) > 300
        result = sanitize_jsx(jsx)
        assert "<svg" in result
        assert "<polygon" in result
        assert "{...}" not in result

    def test_long_raw_markup_ternary_preserved_not_erased(self):
        padding = " ".join(f'data-decoy-{i}="{i}"' for i in range(40))
        jsx = (
            "{ok ? ("
            f'<span {padding}><svg><polygon points="1,2 3,4" /></svg></span>'
            ") : ("
            f'<span {padding}>fallback</span>'
            ")}"
        )
        assert len(jsx) > 300
        result = sanitize_jsx(jsx)
        assert "{...}" not in result
        assert "polygon" in result

    def test_unrelated_long_expression_still_collapsed(self):
        # The generic fallback must still fire for a long expression that
        # is not a markup conditional/ternary — protection is scoped, not a
        # blanket exemption from size bounding.
        long_calc = "{" + "total + ".join(f"item{i}.price" for i in range(60)) + "}"
        assert len(long_calc) > 300
        result = sanitize_jsx(long_calc)
        assert result == "{...}"


class TestExistingBehaviourUnchanged:
    """Guards against regressing the marker system while fixing the tail bug."""

    def test_map_render_gets_list_marker(self):
        jsx = "<ul>{items.map(item => <CartItem key={item.id} />)}</ul>"
        assert "[list:CartItem]" in sanitize_jsx(jsx)

    def test_short_circuit_gets_conditional_marker(self):
        jsx = "<div>{isOpen && <Modal />}</div>"
        assert "[conditional:Modal]" in sanitize_jsx(jsx)

    def test_ternary_two_components_gets_either_marker(self):
        jsx = "<div>{error ? <ErrorBanner /> : <SuccessCard />}</div>"
        assert "[either:ErrorBanner|SuccessCard]" in sanitize_jsx(jsx)

    def test_marker_uses_bracket_notation(self):
        jsx = "<div>{flag && <Sidebar />}</div>"
        assert "{[conditional:Sidebar]}" in sanitize_jsx(jsx)

    def test_no_js_logic_exposed_after_substitution(self):
        jsx = "<div>{isLoggedIn && <UserMenu />}</div>"
        result = sanitize_jsx(jsx)
        assert "isLoggedIn" not in result
        assert "&&" not in result

    def test_map_logic_not_exposed(self):
        jsx = "<ul>{items.map(i => <ListItem />)}</ul>"
        result = sanitize_jsx(jsx)
        assert "items.map" not in result
        assert ".map(" not in result

    def test_static_text_unchanged(self):
        assert "Título fixo" in sanitize_jsx("<h1>Título fixo</h1>")

    def test_preserves_short_jsx_unchanged(self):
        jsx = '<Button style={{color: "red"}}>Click</Button>'
        result = sanitize_jsx(jsx)
        assert "Button" in result
        assert "Click" in result

    def test_handler_still_collapsed(self):
        flat_body = "() => handleMouseEnterEventWithLongNameAndManyParameters(event, index, itemId, extraData)"
        jsx = f'<div onMouseEnter={{{flat_body}}} />'
        result = sanitize_jsx(jsx)
        assert "[handler]" in result
        assert "handleMouseEnter" not in result

    def test_handler_collapse_preserves_event_prop_name(self):
        # A collapsed onChange must stay distinguishable from a collapsed
        # onClick/onBlur — losing the prop name makes every handler on a
        # component look identical to an agent reading the JSX.
        flat_body = "e => setFieldValueFromControlledInputWithValidation(e.target.value, fieldName, index)"
        jsx = f'<input onChange={{{flat_body}}} />'
        result = sanitize_jsx(jsx)
        assert "onChange={[handler]}" in result

    def test_different_handlers_collapse_to_different_markers(self):
        long_click = "() => handleClickWithLoggingAndAnalyticsAndMoreExtraPadding(event, id)"
        long_blur  = "() => handleBlurWithLoggingAndAnalyticsAndMoreExtraPadding(event, id)"
        jsx = f'<button onClick={{{long_click}}} onBlur={{{long_blur}}} />'
        result = sanitize_jsx(jsx)
        assert "onClick={[handler]}" in result
        assert "onBlur={[handler]}" in result

    def test_multiple_markers_in_same_jsx(self):
        jsx = "<div>{items.map(i => <Item />)}{isAdmin && <AdminPanel />}</div>"
        result = sanitize_jsx(jsx)
        assert "[list:Item]" in result
        assert "[conditional:AdminPanel]" in result

    def test_component_name_preserved_in_marker(self):
        jsx = "<div>{flag && <MyComplexComponent />}</div>"
        assert "MyComplexComponent" in sanitize_jsx(jsx)

    def test_ternary_marker_order_is_then_else(self):
        jsx = "<div>{ok ? <ThenComp /> : <ElseComp />}</div>"
        result = sanitize_jsx(jsx)
        assert result.find("ThenComp") < result.find("ElseComp")

    def test_style_between_200_and_400_chars_returned_unchanged(self):
        inner = ", ".join(f"prop{i}: '{10 + i}px'" for i in range(12))
        while len(inner) < 200:
            inner += ", extraFillProp: '1px'"
        assert 200 <= len(inner) <= 299
        result = sanitize_jsx("style={{" + inner + "}}")
        assert "..." not in result
        assert "prop0" in result or "extraFillProp" in result

    def test_style_above_400_chars_collapsed(self):
        inner = ", ".join(f"propNameLong{i}: 'veryLongValue{i}px'" for i in range(18))
        assert len(inner) > 400
        result = sanitize_jsx("style={{" + inner + "}}")
        assert "..." in result

    def test_collapsed_style_block_preserves_both_ternary_branches(self):
        # A collapsed preview must never stop mid-ternary — that's the
        # exact case that made an agent invent a selected-state color the
        # real JSX never stated (Segmented's `background: value === o.value
        # ? ... : ...`).
        ternary_prop = "padding: cond ? '4px 8px' : '6px 10px'"
        filler = ", ".join(f"propNameLong{i}: 'veryLongValue{i}px'" for i in range(14))
        inner = f"{ternary_prop}, {filler}"
        assert len(inner) > 400
        result = sanitize_jsx("style={{" + inner + "}}")
        assert "'4px 8px'" in result
        assert "'6px 10px'" in result

    def test_short_style_kept_intact(self):
        jsx = 'style={{color: "#fff", padding: "8px"}}'
        assert "color" in sanitize_jsx(jsx)

    def test_collapses_very_long_style_blocks(self):
        many_props = ", ".join(f"prop{i}: 'val{i}'" for i in range(50))
        long_style = f"style={{{{ {many_props} }}}}"
        result = sanitize_jsx(long_style)
        assert len(result) < len(long_style)
        assert "..." in result

    def test_collapses_consecutive_blank_lines(self):
        result = sanitize_jsx("line1\n\n\n\n\nline2")
        assert "\n\n\n" not in result

    def test_returns_stripped_string(self):
        result = sanitize_jsx("   <div>x</div>   ")
        assert result == result.strip()

    def test_empty_input_returns_empty(self):
        assert sanitize_jsx("") == ""
