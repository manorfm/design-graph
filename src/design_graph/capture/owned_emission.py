"""Explicit native-event input and emission wrappers, isolated from legacy globals."""
import asyncio
from dataclasses import dataclass, replace

from design_graph.capture.html_prototype.extraction.component_extractor import (
    extract_component,
)
from design_graph.capture.html_prototype.extraction.definition_merge import (
    merge_definitions,
)
from design_graph.capture.html_prototype.extraction.screen_extractor import (
    extract_screens as legacy_screens,
)
from design_graph.capture.html_prototype.sources import FunctionBoundary
from design_graph.model.source_owner import SourceOwnerOrigin, emitted


@dataclass(frozen=True)
class OwnedBoundary(FunctionBoundary):
    origin: SourceOwnerOrigin


def native_boundaries(units, captures, events, flattened):
    boundaries = []; offset = 0; flattened_units = []
    for unit, captured, native in zip(units, captures, events, strict=True):
        text = unit.source.decode(); trimmed = text.strip(); flattened_units.append(trimmed)
        left = len(text) - len(text.lstrip()); ir_unit = captured.lexical.ir.units[0]
        char = lambda byte, source=unit.source: len(source[:byte].decode())
        for event in native:
            name = event['name']
            if event['node_type'] not in ('FunctionDeclaration', 'FunctionExpression') or not name or not name[0].isupper():
                continue
            origin = SourceOwnerOrigin(ir_unit.id, unit.locator, ir_unit.source_sha256, event['native_region'], event['start'], event['end'])
            boundaries.append(OwnedBoundary(name, offset + char(event['start']) - left, offset + char(event['body_start']) - left, offset + char(event['end']) - left, origin))
        offset += len(trimmed) + 1
    if '\n'.join(flattened_units) != flattened:
        raise ValueError('native unit flattening differs from general producer input')
    return sorted(boundaries, key=lambda b: b.start)


def extract_screens(js, all_boundaries):
    screens = []
    for boundary in all_boundaries:
        for screen in legacy_screens(js, [boundary]):
            screens.append(replace(screen, source_owner=emitted('Screen', screen.name, screen.source_code, boundary.origin, js[boundary.start:boundary.end])))
    return screens


async def extract_all_components(js, boundaries, occurrences, concurrency=8, rule_map=None, tag_rule_map=None, responsive_rule_map=None, palette=None, module_constants=None, on_component_extracted=None):
    semaphore = asyncio.Semaphore(concurrency); completed = 0
    async def extract(boundary):
        nonlocal completed
        async with semaphore:
            component = await asyncio.to_thread(extract_component, js, boundary, occurrences.get(boundary.name, 1), rule_map, tag_rule_map, responsive_rule_map, palette, module_constants)
        component = replace(component, source_owner=emitted('Component', component.name, component.source_code, boundary.origin, js[boundary.start:boundary.end]))
        completed += 1
        if on_component_extracted is not None:
            try:
                on_component_extracted(boundary.name, completed, len(boundaries))
            except Exception:  # noqa: BLE001, S110 -- progress observers cannot fail capture.
                pass  # Match the established progress callback isolation.
        return component
    variants = {}
    for component in await asyncio.gather(*(extract(b) for b in boundaries)):
        variants.setdefault(component.name, []).append(component)
    return sorted((merge_definitions(v) for v in variants.values()), key=lambda c: -c.occurrence)
