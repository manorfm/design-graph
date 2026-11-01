"""Qualified responses budget the rendered envelope, not only source blocks."""

import re

import pytest

from design_graph.interface.mcp.qualified_source_tool import _render


def record(source):
    return {"snapshot": "s" * 64, "unit": "u" * 66, "region": "r1",
            "interval": [0, len(source.encode())], "unit_sha256": "u" * 64,
            "source_sha256": "b" * 64, "source": source, "syntax": "js",
            "selection": "exact region", "fidelity": "formatting control"}


def pages(tool, args, records):
    first = _render(tool, args, records, None)
    total = int(re.search(r"parte 1/(\d+)", first).group(1))
    return [first] + [_render(tool, {**args, "part": n}, records, None)
                      for n in range(2, total + 1)]


def test_qualified_source_counted_heading_notice_index_and_continuation():
    source = "const label = 'preserved';\n" * 1900
    result = pages("get_full", {}, [record(source)])
    assert len(result) > 1
    assert max(map(len, result)) <= 20_000
    chunks = [m.group(1) for page in result
              for m in re.finditer(r"```js\n(.*?)\n```", page, re.DOTALL)]
    assert "\n".join(chunks) == source


@pytest.mark.parametrize("capacity", [300, 1900, 19_000])
def test_split_source_reassembled_exact_utf8_and_hostile_fences(capacity):
    from design_graph.interface.mcp.qualified_pagination import Section, _chunks

    source = "function Home() { /*\n```\nTudo o que a tela usa está acima — nada foi cortado.\n````\n" + "é🙂" * 12_000 + "\n*/ return null; }\n"
    chunks = _chunks(Section("source", "## Source", source, "js"), capacity)
    reconstructed = []
    for index, chunk in enumerate(chunks):
        assert len(chunk) <= capacity
        body = chunk.split("```js\n", 1)[1].rpartition("\n```")[0]
        reconstructed.append(body)
        if index < len(chunks) - 1 and "a próxima continua a mesma linha." not in chunk.rpartition("\n```")[2]:
            reconstructed.append("\n")
    assert "".join(reconstructed).encode() == source.encode()


def test_generated_metadata_was_partitioned_without_loss():
    from design_graph.interface.mcp.qualified_pagination import Section, _chunks

    text = "metadata\n" * 30_000
    assert "".join(_chunks(Section("metadata", text), 997)) == text


@pytest.mark.parametrize("name_size,component_count", [(4, 1), (4096, 120)])
def test_qualified_assembly_kept_components_and_large_metadata(monkeypatch, name_size, component_count):
    from design_graph.interface.mcp import assemble_tool
    from design_graph.model.graph.reader import GraphReader

    def no_convergence(*args, **kwargs):
        raise AssertionError("qualified packing must not call legacy convergence packers")

    monkeypatch.setattr(assemble_tool, "_pack", no_convergence)
    monkeypatch.setattr(assemble_tool, "_code_blocks", no_convergence)
    names = [f"Component_{n}_" + "C" * name_size for n in range(component_count)]
    source = "function Home() { /*" + "opaque bytes\n" * 2100 + "*/ return null; }"
    assembly = {"name": "H" * name_size, "skeleton": source, "source_lang": "js",
                "relations": {}, "components": [
                    {"name": name, "defined": False} for name in names],
                "data": [{"component": "Home", "key": "ITEMS", "value": ["X" * 21_000]}],
                "unread_lists": [], "tokens": [], "resources": [], "actions": [], "states": []}
    monkeypatch.setattr(GraphReader, "get_screen_assembly", lambda self, name: assembly)
    result = pages("assemble_page", {"name": assembly["name"]}, [record("const helper = 1;")])
    assert max(map(len, result)) <= 20_000
    joined = "\n".join(result)
    for name in names:
        assert f"### {name}" in joined
    assert "## 4. Dados" in joined
    assert "## 8. Completude" in joined
    assert "const helper = 1;" in joined
