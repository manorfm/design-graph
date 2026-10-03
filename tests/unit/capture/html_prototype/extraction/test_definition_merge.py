"""merge_definitions: same-named definitions of one component merged without loss."""

import pytest

from design_graph.capture.html_prototype.extraction.definition_merge import merge_definitions
from design_graph.model.entities import (
    ComponentType,
    ExtractedComponent,
    IconAsset,
)


class TestExtractedComponentConsolidateSingleVariant:
    def _component(self, jsx: str) -> ExtractedComponent:
        return ExtractedComponent(
            name="Btn", comp_type=ComponentType.BUTTON, source_code=jsx,
            occurrence=1, classes="",
        )

    def test_single_variant_returned_without_any_label_noise(self):
        comp = merge_definitions([self._component("<button>Go</button>")])
        assert comp.source_code == "<button>Go</button>"
        assert "live" not in comp.source_code
        assert "shadowed" not in comp.source_code


class TestExtractedComponentConsolidateChildOrder:
    """C30/T64: order_index should come from the live (last) variant, not a
    sorted union — order is meaningful data now, not just a dedup key."""

    def _component(self, child_refs: list[str]) -> ExtractedComponent:
        return ExtractedComponent(
            name="Shared", comp_type=ComponentType.COMPONENT, source_code="<div/>",
            occurrence=1, classes="", child_refs=child_refs,
        )

    def test_order_comes_from_last_variant(self):
        earlier = self._component(["Alpha", "Beta"])
        live = self._component(["Zebra", "Mango"])
        comp = merge_definitions([earlier, live])
        # Live variant's own order first, then anything only the earlier
        # (shadowed) variant referenced, appended after — union preserved,
        # but the live variant's order takes precedence.
        assert comp.child_refs == ["Zebra", "Mango", "Alpha", "Beta"]

    def test_shared_children_are_not_duplicated(self):
        earlier = self._component(["Alpha", "Beta"])
        live = self._component(["Beta", "Alpha"])
        comp = merge_definitions([earlier, live])
        assert comp.child_refs == ["Beta", "Alpha"]

    def test_single_variant_keeps_its_own_order(self):
        comp = merge_definitions([self._component(["Zebra", "Alpha", "Mango"])])
        assert comp.child_refs == ["Zebra", "Alpha", "Mango"]


class TestExtractedComponentConsolidateMergesIcons:
    def _component(self, icons: list[IconAsset]) -> ExtractedComponent:
        return ExtractedComponent(
            name="Btn", comp_type=ComponentType.BUTTON, source_code="<button/>",
            occurrence=1, classes="", icons=icons,
        )

    def test_icons_from_all_variants_are_merged_and_deduped(self):
        shared = IconAsset.create("<svg><path d=\"M0 0\"/></svg>")
        only_in_second = IconAsset.create("<svg><path d=\"M1 1\"/></svg>")
        variant_a = self._component([shared])
        variant_b = self._component([shared, only_in_second])

        comp = merge_definitions([variant_a, variant_b])

        assert {i.id for i in comp.icons} == {shared.id, only_in_second.id}
        assert len(comp.icons) == 2
