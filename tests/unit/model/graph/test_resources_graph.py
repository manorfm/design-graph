"""Resources are stored once and linked from every screen that loads them."""

import kuzu
import pytest

from design_graph.model.entities import Certainty, ExtractedScreen, Resource, ResourceKind
from design_graph.model.graph.reader import GraphReader
from design_graph.model.graph.schema import initialize_schema
from design_graph.model.graph.writer import GraphWriter

REACT = Resource.create(ResourceKind.LIBRARY, "react", "18.3.1", origin="https://cdn.jsdelivr.net/npm/react@18.3.1",
                        certainty=Certainty.STATED, size=10, sha256="ab")
PLEX = Resource.create(ResourceKind.FONT, "IBM Plex Sans", origin="Google Fonts", certainty=Certainty.INFERRED,
                       detail="pesos 400 · normal", size=5)


@pytest.fixture()
def reader(tmp_path):
    conn = kuzu.Connection(kuzu.Database(str(tmp_path / "res.db")))
    initialize_schema(conn)
    writer = GraphWriter(conn)
    writer.write_resources([REACT, PLEX, REACT])
    writer.write_screen(ExtractedScreen(name="Home", component_refs=[], sections_count=0, resource_ids=[REACT.id, PLEX.id]), [])
    writer.write_screen(ExtractedScreen(name="Sobre", component_refs=[], sections_count=0, resource_ids=[REACT.id]), [])
    writer.commit()
    return GraphReader(conn)


def test_every_resource_is_stored_once(reader):
    assert [(r["name"], r["version"], r["certainty"]) for r in reader.get_resources()] == [
        ("IBM Plex Sans", "", "inferida"), ("react", "18.3.1", "declarada"),
    ]


def test_resources_filter_by_kind_and_screen(reader):
    assert [r["name"] for r in reader.get_resources(kind="library")] == ["react"]
    assert [r["name"] for r in reader.get_resources(screen="Sobre")] == ["react"]
    assert reader.get_resources(screen="Ninguém") == []


def test_a_resource_files_are_stored_once_by_content_and_read_back_whole(tmp_path):
    from design_graph.model.entities import AssetFile

    woff = AssetFile("font/woff2", b"wOF2" + bytes(range(256)))
    font = Resource.create(ResourceKind.FONT, "Plex", origin="embutido no protótipo", certainty=Certainty.STATED,
                           files=(woff, woff))
    conn = kuzu.Connection(kuzu.Database(str(tmp_path / "files.db")))
    initialize_schema(conn)
    writer = GraphWriter(conn)
    writer.write_resources([font])
    writer.commit()
    reader = GraphReader(conn)
    assert reader.get_resource_files("Plex") == [{"sha256": woff.sha256, "mime": "font/woff2", "content": woff.content}]
    assert reader.get_resource_files("Ninguém") == []
