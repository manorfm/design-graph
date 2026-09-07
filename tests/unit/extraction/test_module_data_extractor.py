"""
Tests for module_data_extractor — arbitrary data a component references by
name from a module-level constant (docs/changes/C39), e.g. an icon-name ->
SVG-path lookup table or a role-key -> badge metadata table.
"""

from __future__ import annotations

from design_graph.extraction.module_data_extractor import extract_referenced_module_data

ICONS_LITERAL = '{ lock: "M21 2l-2 2", trash: "M3 6h18", apps: "M3 3h7v7H3z" }'

ROLE_META_LITERAL = (
    '{ root: { bg: "var(--accent-soft)", label: "Root" }, '
    'admin: { bg: "var(--warn-soft)", label: "Admin" } }'
)


class TestExtractReferencedModuleData:
    def test_flat_object_referenced_by_name_is_captured(self):
        body = 'function Icon({ name }) { const d = ICONS[name] || ""; return <svg><path d={d}/></svg>; }'
        result = extract_referenced_module_data(body, {"ICONS": ICONS_LITERAL})
        assert result["ICONS"] == {
            "lock": "M21 2l-2 2", "trash": "M3 6h18", "apps": "M3 3h7v7H3z",
        }

    def test_nested_object_one_level_deep_is_captured(self):
        body = 'function RoleBadge({ role }) { const meta = ROLE_META[role]; return <span>{meta.label}</span>; }'
        result = extract_referenced_module_data(body, {"ROLE_META": ROLE_META_LITERAL})
        assert result["ROLE_META"] == {
            "root": {"bg": "var(--accent-soft)", "label": "Root"},
            "admin": {"bg": "var(--warn-soft)", "label": "Admin"},
        }

    def test_array_literal_referenced_by_name_is_captured(self):
        body = 'function Tabs() { return DETAIL_TABS.map(t => <Tab key={t.key} label={t.label}/>); }'
        tabs_literal = '[{ key: "overview", label: "Visão Geral" }, { key: "menus", label: "Cardápio" }]'
        result = extract_referenced_module_data(body, {"DETAIL_TABS": tabs_literal})
        assert result["DETAIL_TABS"] == [
            {"key": "overview", "label": "Visão Geral"},
            {"key": "menus", "label": "Cardápio"},
        ]

    def test_constant_not_referenced_in_body_is_not_included(self):
        body = "function Btn() { return <button>OK</button>; }"
        result = extract_referenced_module_data(body, {"ICONS": ICONS_LITERAL})
        assert result == {}

    def test_substring_match_is_not_a_reference(self):
        # BIG_ICONS mentions "ICONS" as a substring, but is a different
        # identifier — must not count as a reference to ICONS.
        body = "function Foo() { return BIG_ICONS.default; }"
        result = extract_referenced_module_data(body, {"ICONS": ICONS_LITERAL})
        assert result == {}

    def test_non_string_values_are_dropped_not_guessed(self):
        # icon: SomeImportedIcon (bare identifier) and count: 3 (number)
        # can't be rendered as "the same data" without evaluating JS.
        literal = '{ a: { icon: SomeImportedIcon, count: 3, label: "A" } }'
        body = "function X() { return MIXED[key]; }"
        result = extract_referenced_module_data(body, {"MIXED": literal})
        assert result["MIXED"] == {"a": {"label": "A"}}

    def test_empty_object_yields_no_entry(self):
        body = "function X() { return EMPTY; }"
        result = extract_referenced_module_data(body, {"EMPTY": "{}"})
        assert result == {}

    def test_no_module_constants_returns_empty_dict(self):
        body = "function Icon({ name }) { const d = ICONS[name]; return null; }"
        assert extract_referenced_module_data(body, {}) == {}

    def test_third_level_of_object_nesting_is_not_expanded(self):
        # One level deeper than the real ROLE_META shape this was written
        # against (docs/changes/C39) — deliberately not expanded, not a bug.
        literal = '{ a: { b: { c: "too deep" } } }'
        body = "function X() { return DEEP[key]; }"
        result = extract_referenced_module_data(body, {"DEEP": literal})
        assert result == {}
