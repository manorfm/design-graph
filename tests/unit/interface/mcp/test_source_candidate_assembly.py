"""Normal dispatch over a real BUILD; no request-qualified source parameters."""
from pathlib import Path

import pytest

from design_graph.interface.mcp.tools import ToolDispatcher
from design_graph.model.graph.reader import GraphReader
from tests.unit.pipeline.test_binding_cli import build
from tests.unit.pipeline.test_binding_cli_controls import open_db

HELPER = 'function hue(){return PALETTE[0]}'
PALETTE = 'const PALETTE=[47,153];'
HTML = ('<html><body><script>\n' + PALETTE + '\n' + HELPER + '\nwindow.Lib={hue};\n</script>'
        '<script>\nconst K=window.Lib;\nfunction Avatar(){return <b>{K.hue()}</b>}\n'
        'function MainPage(){return <Avatar/>}\n</script></body></html>')


@pytest.fixture
def normal(tmp_path):
    source = tmp_path / 'input.html'
    source.write_text(HTML)
    path = tmp_path / 'fresh.db'
    result = build(source, path)
    assert result.returncode == 0, result.stderr
    database, connection = open_db(path)
    reader = GraphReader(connection, Path(str(path) + '.state.json'))
    try:
        yield ToolDispatcher([('fresh', reader)]), reader, path
    finally:
        connection.close()
        database.close()


def test_normal_source_delivered_native_member_and_lexical_context(normal):
    dispatcher, _, _ = normal
    text = dispatcher.dispatch('get_full', {'name': 'Avatar', 'aspect': 'source'}, '')
    assert text.count(HELPER) == 1 and text.count(PALETTE) == 1
    assert 'runtime_claim=false' in text and 'global-writes-unknown' in text
    assert 'enclosing native scope, NOT exact declaration owner' in text


def test_normal_assembly_delivered_once_even_known(normal):
    dispatcher, _, _ = normal
    args = {'name': 'MainPage', 'known': ['Avatar']}
    text = dispatcher.dispatch('assemble_page', args, '')
    assert text.count(HELPER) == 1 and text.count(PALETTE) == 1
    assert text == dispatcher.dispatch('assemble_page', args, '')
    assert 'source closure incomplete/unknown' in text


@pytest.mark.parametrize('target', ['selected', 'unselected'])
def test_next_same_connection_rejected_changed_field(normal, target):
    dispatcher, reader, _ = normal
    args = {'name': 'Avatar', 'aspect': 'source'}
    assert HELPER in dispatcher.dispatch('get_full', args, '')
    name = 'Avatar' if target == 'selected' else 'MainPage'
    reader._conn.execute('MATCH (n) WHERE n.name=$name SET n.source_code=$source', {'name': name, 'source': 'changed'}).close()
    assert HELPER not in dispatcher.dispatch('get_full', args, '')


def test_missing_completion_preserved_legacy_source(normal):
    dispatcher, _, path = normal
    Path(str(path) + '.binding.json').unlink()
    text = dispatcher.dispatch('get_full', {'name': 'Avatar', 'aspect': 'source'}, '')
    assert 'function Avatar' in text and HELPER not in text


def test_normal_unknown_name_never_selected_helper_by_name(normal):
    dispatcher, _, _ = normal
    text = dispatcher.dispatch('get_full', {'name': 'hue', 'aspect': 'source'}, '')
    assert 'ownership/correspondence unknown' in text
    assert HELPER not in text


@pytest.mark.parametrize('part', [True, False, 0, -1, '1'])
def test_normal_source_refused_nonpositive_or_noninteger_part(normal, part):
    dispatcher, _, _ = normal
    with pytest.raises(ValueError, match='part'):
        dispatcher.dispatch('get_full', {'name': 'Avatar', 'aspect': 'source', 'part': part}, '')


@pytest.mark.parametrize('part', [True, False, 0, -1, '1'])
def test_normal_assembly_refused_noninteger_part(normal, part):
    dispatcher, _, _ = normal
    with pytest.raises(ValueError, match='part'):
        dispatcher.dispatch('assemble_page', {'name': 'MainPage', 'part': part}, '')


def test_reader_selection_remained_explicit(normal):
    _, reader, _ = normal
    dispatcher = ToolDispatcher([('first', reader), ('second', reader)])
    args = {'name': 'Avatar', 'aspect': 'source'}
    assert 'Multiple prototypes' in dispatcher.dispatch('get_full', args, '')
    assert HELPER in dispatcher.dispatch('get_full', args, 'second')
    assert HELPER in dispatcher.dispatch('get_full', {**args, 'doc': 'first'}, 'second')
