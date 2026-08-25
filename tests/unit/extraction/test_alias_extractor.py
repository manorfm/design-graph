"""
Tests for alias_extractor — resolves re-export bindings such as
`const Badge = window.V6K.Pill;` to the component they point at, so JSX
references to the alias name don't end up as an empty unresolved shell.
"""

from __future__ import annotations

import pytest

from design_graph.extraction.alias_extractor import (
    ComponentAlias,
    apply_aliases,
    extract_component_aliases,
)


class TestComponentAlias:
    def test_rejects_self_referential_alias(self):
        with pytest.raises(ValueError, match="itself"):
            ComponentAlias(name="Badge", target="Badge")


class TestExtractComponentAliases:
    def test_finds_alias_when_target_is_known(self):
        js = "const Badge = window.V6K.Pill;"
        aliases = extract_component_aliases(js, known_component_names={"Pill"})
        assert aliases == {"Badge": "Pill"}

    def test_ignores_alias_when_target_is_not_a_known_component(self):
        # "Pill" was never extracted as a component — nothing to point at,
        # so treating "Badge" as unresolved is more honest than guessing.
        js = "const Badge = window.V6K.Pill;"
        aliases = extract_component_aliases(js, known_component_names=set())
        assert aliases == {}

    def test_ignores_plain_reassignment_without_member_access(self):
        # No `.Member` on the right-hand side — not a re-export pattern.
        js = "const Badge = Pill;"
        aliases = extract_component_aliases(js, known_component_names={"Pill"})
        assert aliases == {}

    def test_ignores_function_call_right_hand_side(self):
        # RE_COMP_ARROW_FN's job, not ours — this defines a new component.
        js = "const Badge = (props) => <Pill {...props} />;"
        aliases = extract_component_aliases(js, known_component_names={"Pill"})
        assert aliases == {}

    def test_resolves_deeper_namespace_chains(self):
        js = "const Btn = App.UI.Buttons.Primary;"
        aliases = extract_component_aliases(js, known_component_names={"Primary"})
        assert aliases == {"Btn": "Primary"}

    def test_finds_multiple_independent_aliases(self):
        js = """
        const Badge = window.V6K.Pill;
        const Tag = window.V6K.Chip;
        """
        aliases = extract_component_aliases(js, known_component_names={"Pill", "Chip"})
        assert aliases == {"Badge": "Pill", "Tag": "Chip"}

    def test_skips_self_referential_alias_without_crashing(self):
        # Degenerate but syntactically valid in minified/generated code —
        # a single bad binding must not abort extraction for the whole file.
        js = """
        const Pill = ns.Pill;
        const Badge = window.V6K.Pill;
        """
        aliases = extract_component_aliases(js, known_component_names={"Pill"})
        assert aliases == {"Badge": "Pill"}


class TestApplyAliases:
    def test_substitutes_alias_with_target(self):
        refs = ["Badge", "Btn"]
        result = apply_aliases(refs, aliases={"Badge": "Pill"})
        assert result == ["Pill", "Btn"]

    def test_preserves_original_appearance_order(self):
        # C34: must not re-alphabetize — refs is render-order data (see
        # component_extractor's own first-appearance ordering), and this
        # runs unconditionally on every entity as soon as one alias exists
        # anywhere in the bundle.
        refs = ["Zebra", "Badge", "Alpha"]
        result = apply_aliases(refs, aliases={"Badge": "Pill"})
        assert result == ["Zebra", "Pill", "Alpha"]

    def test_no_op_when_no_refs_match_an_alias(self):
        refs = ["Btn", "Card"]
        result = apply_aliases(refs, aliases={"Badge": "Pill"})
        assert result == ["Btn", "Card"]

    def test_dedupes_when_alias_and_target_both_referenced(self):
        # Some other component already references Pill directly; substituting
        # Badge → Pill here must not produce a duplicate entry.
        refs = ["Badge", "Pill"]
        result = apply_aliases(refs, aliases={"Badge": "Pill"})
        assert result == ["Pill"]

    def test_empty_refs_returns_empty_list(self):
        assert apply_aliases([], aliases={"Badge": "Pill"}) == []
