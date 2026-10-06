"""
get_asset writes a resource's files (a font family, an image) into the
workspace, under design-graph-assets/, and says where — never anywhere else,
never under a name taken from the prototype.
"""

import hashlib

import pytest

from design_graph.interface.mcp.asset_tool import ASSETS_DIR, get_asset

WOFF = b"wOF2" + bytes(range(64))
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"/>'


class _Reader:
    def __init__(self, files):
        self.files = files

    def get_resource_files(self, name):
        return self.files.get(name, [])


def _file(content, mime):
    return {"sha256": hashlib.sha256(content).hexdigest(), "mime": mime, "content": content}


@pytest.fixture()
def reader():
    return _Reader({
        "IBM Plex Sans": [_file(WOFF, "font/woff2")],
        "favicon": [_file(SVG, "image/svg+xml")],
        "../../etc/passwd": [_file(SVG, "image/svg+xml")],
        "adulterado": [{"sha256": "0" * 64, "mime": "image/svg+xml", "content": SVG}],
    })


def test_files_are_written_under_the_assets_folder_and_listed(tmp_path, reader):
    out = get_asset(reader, "IBM Plex Sans", tmp_path)
    written = list((tmp_path / ASSETS_DIR / "ibm-plex-sans").iterdir())
    assert [p.read_bytes() for p in written] == [WOFF]
    assert written[0].name == f"{hashlib.sha256(WOFF).hexdigest()[:16]}.woff2"
    assert f"{ASSETS_DIR}/ibm-plex-sans/{written[0].name}" in out


def test_writing_twice_keeps_one_copy(tmp_path, reader):
    get_asset(reader, "favicon", tmp_path)
    get_asset(reader, "favicon", tmp_path)
    assert len(list((tmp_path / ASSETS_DIR / "favicon").iterdir())) == 1


def test_a_hostile_name_never_leaves_the_assets_folder(tmp_path, reader):
    get_asset(reader, "../../etc/passwd", tmp_path)
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written and all(p.resolve().is_relative_to((tmp_path / ASSETS_DIR).resolve()) for p in written)


def test_a_symlinked_assets_folder_is_refused(tmp_path, reader):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / ASSETS_DIR).symlink_to(elsewhere)
    assert "Recusado" in get_asset(reader, "favicon", tmp_path)
    assert not any(elsewhere.iterdir())


def test_content_that_does_not_match_its_hash_is_not_written(tmp_path, reader):
    assert "não confere" in get_asset(reader, "adulterado", tmp_path)
    assert not (tmp_path / ASSETS_DIR / "adulterado").exists() or not any((tmp_path / ASSETS_DIR / "adulterado").iterdir())


def test_a_resource_without_files_says_so(tmp_path, reader):
    assert "Nenhum arquivo" in get_asset(reader, "react", tmp_path)
