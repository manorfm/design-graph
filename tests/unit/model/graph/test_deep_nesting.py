"""A component nested however deep is still reached from the screens that render it."""

import kuzu

from design_graph.model.entities import DesignToken, ExtractedComponent, ExtractedScreen, StyleEntry
from design_graph.model.graph.reader import GraphReader
from design_graph.model.graph.schema import initialize_schema
from design_graph.model.graph.writer import GraphWriter

DEPTH = 7  # deeper than the three levels the reader once stopped at


def _chain_graph(tmp_path) -> GraphReader:
    conn = kuzu.Connection(kuzu.Database(str(tmp_path / "deep.db")))
    initialize_schema(conn)
    w = GraphWriter(conn)
    w.write_tokens([DesignToken(id="deep_ink", category="css_var", label="--deep-ink", value="#123456", usage=1)])
    names = [f"Level{n}" for n in range(DEPTH + 1)]
    for index, name in enumerate(names):
        child = names[index + 1: index + 2]
        styles = [StyleEntry.create(name, "color", "var(--deep-ink)")] if index == DEPTH else []
        w.write_component(ExtractedComponent(name=name, comp_type="component", source_code=f"<div>{name}</div>",
                                             occurrence=1, classes="", child_refs=child, styles=styles))
    w.flush_pending_contains()  # as the pipeline does: a parent may be written before its children
    w.write_screen(ExtractedScreen(name="Laudo", component_refs=["Level0"], sections_count=0, source_code=""), [])
    w.commit()
    return GraphReader(conn)


def test_the_deepest_component_is_used_by_the_screen(tmp_path):
    reader = _chain_graph(tmp_path)
    assert reader.find_screens_using_comp_transitively(f"Level{DEPTH}") == ["Laudo"]
    assert reader.get_impact(f"Level{DEPTH}")["screens"] == ["Laudo"]


def test_the_screen_tokens_include_those_of_its_deepest_component(tmp_path):
    reader = _chain_graph(tmp_path)
    assert "--deep-ink" in {t["t.label"] for t in reader.get_tokens(screen="Laudo")}
