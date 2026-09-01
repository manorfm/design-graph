"""Tests for value objects and enums in core/models.py — DDD refactor."""

import hashlib

import pytest

from design_graph.core.models import (
    ComponentProp,
    ComponentType,
    DetectionMethod,
    EntityId,
    ExtractedComponent,
    ExtractedSection,
    IconAsset,
    InteractionEntry,
    InteractionTrigger,
    JsxMarker,
    JsxMarkerKind,
    JsxSnippet,
    PropDefault,
    SemanticType,
    SourceFormat,
    StyleEntry,
    StyleState,
    TextEntry,
    TextType,
    TokenCategory,
)


class TestEntityIdDerive:
    def test_format_is_prefix_underscore_eight_hex_chars(self):
        eid = EntityId.derive("st", "BtnPrimary_backgroundColor_#ffb81c")
        prefix, _, digest = eid.partition("_")
        assert prefix == "st"
        assert len(digest) == 8
        assert all(c in "0123456789abcdef" for c in digest)

    def test_same_seed_produces_same_id(self):
        a = EntityId.derive("int", "RestCard_border_C.accent")
        b = EntityId.derive("int", "RestCard_border_C.accent")
        assert a == b

    def test_different_seed_produces_different_id(self):
        a = EntityId.derive("int", "RestCard_border_C.accent")
        b = EntityId.derive("int", "RestCard_border_C.red")
        assert a != b

    def test_different_prefix_produces_different_id_for_same_seed(self):
        a = EntityId.derive("st", "shared_seed")
        b = EntityId.derive("cls", "shared_seed")
        assert a != b

    def test_matches_legacy_prefix_plus_md5_hexdigest_eight_algorithm(self):
        # Byte-compatibility guarantee: existing IDs already written to graphs
        # (and used for incremental-build diffing) must not change format.
        seed = "OptRow_borderColor_C.red"
        expected = "st_" + hashlib.md5(seed.encode()).hexdigest()[:8]
        assert EntityId.derive("st", seed) == expected


class TestEntityIdLiteral:
    def test_format_is_prefix_underscore_suffix(self):
        eid = EntityId.literal("sp", "16")
        assert eid == "sp_16"

    def test_matches_legacy_fstring_id_for_spacing_tokens(self):
        grid_px = 24
        expected = f"sp_{grid_px}"
        assert EntityId.literal("sp", str(grid_px)) == expected


class TestEntityIdBehavesAsString:
    def test_is_instance_of_str(self):
        eid = EntityId.derive("txt", "seed")
        assert isinstance(eid, str)

    def test_equal_to_plain_string_with_same_value(self):
        eid = EntityId.literal("prop", "abc123")
        assert eid == "prop_abc123"

    def test_usable_as_dict_key_matching_plain_string(self):
        eid = EntityId.literal("sec", "hero")
        d = {eid: "value"}
        assert d["sec_hero"] == "value"

    def test_json_serializes_as_plain_string(self):
        import json
        eid = EntityId.derive("col", "seed")
        assert json.dumps({"id": eid}) == json.dumps({"id": str(eid)})


# ── Enums ──────────────────────────────────────────────────────────────────────

class TestStyleState:
    def test_members(self):
        assert {m.value for m in StyleState} == {"default", "hover", "focus"}

    def test_dead_member_removed(self):
        assert not hasattr(StyleState, "TRANSITION")

    def test_equals_plain_string(self):
        assert StyleState.HOVER == "hover"

    def test_str_and_fstring_produce_plain_value_not_class_dot_member(self):
        # (str, Enum) alone would render "StyleState.HOVER" here — Enum.__str__
        # shadows str.__str__. This is exactly the bug that broke id-derivation
        # seeds built via f-string; guard it for every enum, not just this one.
        assert str(StyleState.HOVER) == "hover"
        assert f"{StyleState.HOVER}" == "hover"


class TestInteractionTrigger:
    def test_members(self):
        assert {m.value for m in InteractionTrigger} == {"hover", "focus"}


class TestTextType:
    def test_members(self):
        assert {m.value for m in TextType} == {
            "heading", "button", "label", "placeholder", "description", "section_text", "tooltip",
        }


class TestTokenCategory:
    def test_members(self):
        assert {m.value for m in TokenCategory} == {
            "color", "spacing", "typography", "shadow", "radius", "css_var",
        }


class TestSourceFormat:
    def test_members(self):
        assert {m.value for m in SourceFormat} == {"bundled_react", "tailwind", "plain_html"}


class TestDetectionMethod:
    def test_members(self):
        assert {m.value for m in DetectionMethod} == {
            "comment", "structural", "semantic", "list_item",
        }

    def test_dead_member_removed(self):
        assert not hasattr(DetectionMethod, "NONE")


class TestComponentType:
    def test_members(self):
        assert {m.value for m in ComponentType} == {
            "modal", "screen", "button", "card", "tab", "form", "list-item",
            "badge", "chart", "navigation", "toggle", "table", "component",
        }


class TestSemanticType:
    def test_members(self):
        assert {m.value for m in SemanticType} == {
            "nav", "header", "footer", "card", "modal", "badge", "form",
            "table", "list-item", "component",
        }


# ── PropDefault ────────────────────────────────────────────────────────────────

class TestPropDefault:
    """
    JSX has no required/optional prop system, so "no default declared" is not
    proof a prop is required — a prop is routinely omitted at call sites
    (guarded by `&&`, safely undefined, etc.) with no default in sight.
    PropDefault only reports what's verifiable: whether a default was
    declared, and what it is — never a required/optional claim.
    """

    def test_empty_was_not_declared(self):
        assert PropDefault("").was_declared is False

    def test_non_empty_was_declared(self):
        assert PropDefault("primary").was_declared is True

    def test_behaves_as_plain_string(self):
        assert PropDefault("false") == "false"

    def test_table_cell_is_a_dash_when_not_declared(self):
        assert PropDefault("").as_table_cell() == "—"

    def test_table_cell_is_backticked_value_when_declared(self):
        assert PropDefault("secondary").as_table_cell() == "`secondary`"


# ── JsxMarker ──────────────────────────────────────────────────────────────────

class TestJsxMarker:
    def test_list_marker_renders_single_name(self):
        marker = JsxMarker(JsxMarkerKind.LIST, ("CartItem",))
        assert str(marker) == "{[list:CartItem]}"

    def test_conditional_marker_renders_single_name(self):
        marker = JsxMarker(JsxMarkerKind.CONDITIONAL, ("Badge",))
        assert str(marker) == "{[conditional:Badge]}"

    def test_either_marker_renders_both_names_in_order(self):
        marker = JsxMarker(JsxMarkerKind.EITHER, ("SuccessCard", "ErrorBanner"))
        assert str(marker) == "{[either:SuccessCard|ErrorBanner]}"

    def test_conditional_rejects_two_names(self):
        with pytest.raises(ValueError):
            JsxMarker(JsxMarkerKind.CONDITIONAL, ("A", "B"))

    def test_list_rejects_zero_names(self):
        with pytest.raises(ValueError):
            JsxMarker(JsxMarkerKind.LIST, ())

    def test_either_rejects_single_name(self):
        with pytest.raises(ValueError):
            JsxMarker(JsxMarkerKind.EITHER, ("A",))

    def test_either_rejects_three_names(self):
        with pytest.raises(ValueError):
            JsxMarker(JsxMarkerKind.EITHER, ("A", "B", "C"))


# ── JsxSnippet ────────────────────────────────────────────────────────────────

class TestJsxSnippet:
    def test_plain_jsx_is_not_flagged_as_sanitized(self):
        snippet = JsxSnippet("<button style={{color: '#fff'}}>Click</button>")
        assert snippet.was_sanitized is False

    def test_empty_snippet_is_not_flagged_as_sanitized(self):
        assert JsxSnippet("").was_sanitized is False

    def test_list_marker_flags_as_sanitized(self):
        assert JsxSnippet("<div>{[list:CartItem]}</div>").was_sanitized is True

    def test_conditional_marker_flags_as_sanitized(self):
        assert JsxSnippet("<div>{[conditional:Badge]}</div>").was_sanitized is True

    def test_either_marker_flags_as_sanitized(self):
        assert JsxSnippet("<div>{[either:A|B]}</div>").was_sanitized is True

    def test_handler_marker_flags_as_sanitized(self):
        assert JsxSnippet("<input onChange={[handler]} />").was_sanitized is True

    def test_arrow_fn_marker_flags_as_sanitized(self):
        assert JsxSnippet("{items.map.[fn]}").was_sanitized is True

    def test_collapsed_style_block_flags_as_sanitized(self):
        assert JsxSnippet("style={{ color: red, ... }}").was_sanitized is True

    def test_bare_expression_marker_flags_as_sanitized(self):
        assert JsxSnippet("<div>{...}</div>").was_sanitized is True

    def test_still_behaves_as_a_plain_string(self):
        snippet = JsxSnippet("<div />")
        assert snippet == "<div />"
        assert "div" in snippet


# ── Rich entity factories ─────────────────────────────────────────────────────

class TestStyleEntryCreate:
    def test_default_state_seed_excludes_state_name(self):
        # Byte-compat: legacy default-state ids never included "default" in the seed.
        expected = "st_" + hashlib.md5(b"BtnPrimary_backgroundColor_#ffb81c").hexdigest()[:8]
        entry = StyleEntry.create(element="BtnPrimary", property="backgroundColor", value="#ffb81c")
        assert entry.id == expected
        assert entry.state == StyleState.DEFAULT

    def test_hover_state_seed_includes_state_name(self):
        expected = "st_" + hashlib.md5(b"BtnPrimary_hover_backgroundColor_#f59e0b").hexdigest()[:8]
        entry = StyleEntry.create(
            element="BtnPrimary", property="backgroundColor", value="#f59e0b", state=StyleState.HOVER,
        )
        assert entry.id == expected

    def test_from_css_class_matches_legacy_seed(self):
        expected = "cls_" + hashlib.md5(b"flex:display").hexdigest()[:8]
        entry = StyleEntry.from_css_class(class_name="flex", property="display", value="flex")
        assert entry.id == expected
        assert entry.element == "class:flex"
        assert entry.state == StyleState.DEFAULT

    def test_from_css_class_hover_state_seed_includes_state_name(self):
        # C29/T61: hover:/focus: variants must not collide with the default-state id.
        expected = "cls_" + hashlib.md5(b"flex:hover:display").hexdigest()[:8]
        entry = StyleEntry.from_css_class(
            class_name="flex", property="display", value="flex", state=StyleState.HOVER,
        )
        assert entry.id == expected
        assert entry.state == StyleState.HOVER

    def test_from_css_class_default_and_hover_ids_differ(self):
        default_entry = StyleEntry.from_css_class(class_name="flex", property="display", value="flex")
        hover_entry = StyleEntry.from_css_class(
            class_name="flex", property="display", value="flex", state=StyleState.HOVER,
        )
        assert default_entry.id != hover_entry.id

    def test_for_section_matches_legacy_seed(self):
        expected = "sec_" + hashlib.md5(b"sec_abc123_padding").hexdigest()[:8]
        entry = StyleEntry.for_section(section_id="sec_abc123", property="padding", value="16px")
        assert entry.id == expected
        assert entry.element == "sec_abc123"


class TestTextEntryCreate:
    def test_create_matches_legacy_seed(self):
        expected = "txt_" + hashlib.md5(b"BtnPrimary_Confirmar").hexdigest()[:8]
        entry = TextEntry.create(
            content="Confirmar", text_type=TextType.BUTTON, source="BtnPrimary", element="button",
        )
        assert entry.id == expected

    def test_for_section_matches_legacy_seed(self):
        expected = "stxt_" + hashlib.md5(b"sec_abc123_Bem-vindo").hexdigest()[:8]
        entry = TextEntry.for_section(section_id="sec_abc123", text="Bem-vindo")
        assert entry.id == expected
        assert entry.text_type == TextType.SECTION_TEXT
        assert entry.source == "sec_abc123"
        assert entry.element == "section"


class TestTextEntryIsPlausibleContent:
    """
    component_extractor._add_text carried this exact filter inline as a
    local closure — the only place a raw string candidate was ever
    classified as "real UI copy" vs a code artifact. A second extractor
    (module-level constant-array text) needs the identical judgment call;
    duplicating the filter would let the two definitions of "plausible"
    drift apart. Moved onto TextEntry itself: it's a fact about the value
    type, not about the extractor that happens to be running.
    """

    def test_normal_sentence_is_plausible(self):
        assert TextEntry.is_plausible_content("Cardápio & Preço") is True

    def test_too_short_is_not_plausible(self):
        assert TextEntry.is_plausible_content("Ok") is False

    def test_too_long_is_not_plausible(self):
        assert TextEntry.is_plausible_content("x" * 81) is False

    def test_lowercase_identifier_shaped_is_not_plausible(self):
        assert TextEntry.is_plausible_content("flex_start") is False

    def test_hex_color_is_not_plausible(self):
        assert TextEntry.is_plausible_content("#1a1a1a") is False

    def test_rgba_color_is_not_plausible(self):
        assert TextEntry.is_plausible_content("rgba(0,0,0,.5)") is False

    def test_empty_is_not_plausible(self):
        assert TextEntry.is_plausible_content("") is False

    def test_surrounding_whitespace_is_stripped_before_judging(self):
        assert TextEntry.is_plausible_content("  Mesas  ") is True


class TestInteractionEntryCreate:
    def test_create_matches_legacy_seed(self):
        expected = "int_" + hashlib.md5(b"BtnPrimary_backgroundColor_#f59e0b").hexdigest()[:8]
        entry = InteractionEntry.create(
            trigger=InteractionTrigger.HOVER, css_prop="backgroundColor",
            from_val="#ffb81c", to_val="#f59e0b", transition="all 0.2s ease",
            element="BtnPrimary",
        )
        assert entry.id == expected

    def test_from_focus_mutation_matches_legacy_seed(self):
        # Imperative onFocus mutations seed differently: no to_val, literal "focus" instead.
        expected = "int_" + hashlib.md5(b"TextInput_focus_borderColor").hexdigest()[:8]
        entry = InteractionEntry.from_focus_mutation(
            element="TextInput", css_prop="borderColor", to_val="#ffb81c", transition="all 0.15s",
        )
        assert entry.id == expected
        assert entry.trigger == InteractionTrigger.FOCUS
        assert entry.from_val == ""


class TestComponentPropCreate:
    def test_create_matches_legacy_seed(self):
        expected = "prop_" + hashlib.md5(b"NavBar_onClose").hexdigest()[:8]
        prop = ComponentProp.create(component_name="NavBar", prop_name="onClose", default_value="")
        assert prop.id == expected
        assert prop.default_value.was_declared is False


class TestExtractedSectionCreate:
    def test_create_matches_legacy_seed(self):
        expected = "sec_" + hashlib.md5(b"HomeScreen_Header").hexdigest()[:8]
        section = ExtractedSection.create(
            screen="HomeScreen", name="Header", styles={}, component_refs=[],
            texts=[], jsx_snippet="", detection_method=DetectionMethod.COMMENT,
        )
        assert section.id == expected

    def test_create_semantic_matches_legacy_seed(self):
        expected = "sec_" + hashlib.md5(b"HomeScreen_Nav_0").hexdigest()[:8]
        section = ExtractedSection.create_semantic(
            screen="HomeScreen", name="Nav", index=0, texts=[], jsx_snippet="",
        )
        assert section.id == expected
        assert section.detection_method == DetectionMethod.SEMANTIC

    def test_element_styles_defaults_to_empty_list(self):
        section = ExtractedSection.create(
            screen="HomeScreen", name="Header", styles={}, component_refs=[],
            texts=[], jsx_snippet="", detection_method=DetectionMethod.COMMENT,
        )
        assert section.element_styles == []

    def test_element_styles_preserves_per_selector_entries(self):
        entries = [
            StyleEntry.from_css_class("audit-item", "display", "grid"),
            StyleEntry.from_css_class("audit-dot", "display", "flex"),
        ]
        section = ExtractedSection.create(
            screen="HistoryView", name="Audit item", styles={}, component_refs=[],
            texts=[], jsx_snippet="", detection_method=DetectionMethod.LIST_ITEM,
            element_styles=entries,
        )
        assert section.element_styles == entries
        elements = {entry.element for entry in section.element_styles}
        assert elements == {"class:audit-item", "class:audit-dot"}


class TestExtractedComponentConsolidateSingleVariant:
    def _component(self, jsx: str) -> ExtractedComponent:
        return ExtractedComponent(
            name="Btn", comp_type=ComponentType.BUTTON, jsx_snippet=jsx,
            occurrence=1, classes="",
        )

    def test_single_variant_returned_without_any_label_noise(self):
        comp = ExtractedComponent.consolidate([self._component("<button>Go</button>")])
        assert comp.jsx_snippet == "<button>Go</button>"
        assert "live" not in comp.jsx_snippet
        assert "shadowed" not in comp.jsx_snippet


# ── Deduplicated icon assets ────────────────────────────────────────────────────

class TestIconAssetCreate:
    def test_id_is_deterministic_hash_of_markup(self):
        markup = '<svg viewBox="0 0 24 24"><path d="M12 2L2 7"/></svg>'
        expected = "icon_" + hashlib.md5(markup.encode()).hexdigest()[:8]
        icon = IconAsset.create(markup)
        assert icon.id == expected
        assert icon.markup == markup

    def test_identical_markup_produces_identical_id(self):
        markup = "<svg><path d=\"M0 0\"/></svg>"
        assert IconAsset.create(markup).id == IconAsset.create(markup).id

    def test_different_markup_produces_different_id(self):
        a = IconAsset.create("<svg><path d=\"M0 0\"/></svg>")
        b = IconAsset.create("<svg><path d=\"M1 1\"/></svg>")
        assert a.id != b.id

    def test_str_renders_bracket_marker(self):
        icon = IconAsset.create("<svg><circle/></svg>")
        assert str(icon) == f"{{[icon:{icon.id}]}}"


class TestExtractedComponentConsolidateChildOrder:
    """C30/T64: order_index should come from the live (last) variant, not a
    sorted union — order is meaningful data now, not just a dedup key."""

    def _component(self, child_refs: list[str]) -> ExtractedComponent:
        return ExtractedComponent(
            name="Shared", comp_type=ComponentType.COMPONENT, jsx_snippet="<div/>",
            occurrence=1, classes="", child_refs=child_refs,
        )

    def test_order_comes_from_last_variant(self):
        earlier = self._component(["Alpha", "Beta"])
        live = self._component(["Zebra", "Mango"])
        comp = ExtractedComponent.consolidate([earlier, live])
        # Live variant's own order first, then anything only the earlier
        # (shadowed) variant referenced, appended after — union preserved,
        # but the live variant's order takes precedence.
        assert comp.child_refs == ["Zebra", "Mango", "Alpha", "Beta"]

    def test_shared_children_are_not_duplicated(self):
        earlier = self._component(["Alpha", "Beta"])
        live = self._component(["Beta", "Alpha"])
        comp = ExtractedComponent.consolidate([earlier, live])
        assert comp.child_refs == ["Beta", "Alpha"]

    def test_single_variant_keeps_its_own_order(self):
        comp = ExtractedComponent.consolidate([self._component(["Zebra", "Alpha", "Mango"])])
        assert comp.child_refs == ["Zebra", "Alpha", "Mango"]


class TestExtractedComponentConsolidateMergesIcons:
    def _component(self, icons: list[IconAsset]) -> ExtractedComponent:
        return ExtractedComponent(
            name="Btn", comp_type=ComponentType.BUTTON, jsx_snippet="<button/>",
            occurrence=1, classes="", icons=icons,
        )

    def test_icons_from_all_variants_are_merged_and_deduped(self):
        shared = IconAsset.create("<svg><path d=\"M0 0\"/></svg>")
        only_in_second = IconAsset.create("<svg><path d=\"M1 1\"/></svg>")
        variant_a = self._component([shared])
        variant_b = self._component([shared, only_in_second])

        comp = ExtractedComponent.consolidate([variant_a, variant_b])

        assert {i.id for i in comp.icons} == {shared.id, only_in_second.id}
        assert len(comp.icons) == 2
