"""Native-owned general fields must survive the normal capture/build route."""
import asyncio
from pathlib import Path

from design_graph.capture.base import PrototypeDocument
from design_graph.pipeline.binding_build import BindingBuildOptions, BindingStage
from tests.unit.model.test_binding_capture import provider


def test_normal_native_capture_retained_field_owner(tmp_path):
    p = provider()
    path = tmp_path / 'owned.html'
    path.write_text('<html><body><script>function Avatar(){return <b>hello</b>} function MainPage(){return <Avatar/>}</script></body></html>')
    stage = BindingStage(PrototypeDocument.read(path), BindingBuildOptions(p.node, p.toolchain, p.fingerprint))
    stage.capture('owned')
    assert callable(getattr(stage, 'capture_general', None)), 'normal capture discarded native owner events'
    result = asyncio.run(stage.capture_general(concurrency=2))
    avatar = next(c for c in result.components if c.name == 'Avatar')
    assert avatar.source_owner.mapping == 'exact-slice'
    assert avatar.source_owner.native_region == 'r1'
    assert avatar.source_owner.payload_sha256


import dataclasses
import hashlib
import json

import pytest

from design_graph.model.graph.source_build_ownership import PayloadOwner
from design_graph.model.source_owner import check_witnesses


@pytest.fixture
def owned(tmp_path):
    p = provider()
    path = tmp_path / 'unicode.html'
    path.write_text('<html><body><script>const astral="😀"; function Avatar(){return <b>é😀</b>} function MainPage(){return <Avatar/>}</script></body></html>')
    stage = BindingStage(PrototypeDocument.read(path), BindingBuildOptions(p.node, p.toolchain, p.fingerprint))
    stage.capture('unicode')
    result = asyncio.run(stage.capture_general(concurrency=2))
    w = next(c.source_owner for c in result.components if c.name == 'Avatar')
    owner = PayloadOwner(w.table,w.key,w.field,'0'*64,w.payload_sha256)
    return stage,w,owner


def test_unicode_exact_native_identity(owned):
    stage,w,owner = owned
    check_witnesses((w,), (owner,), stage.syntax)
    o=w.origins[0]
    raw=stage.syntax.captures[0].lexical.ir.units[0].source.encode()[o.start:o.end]
    assert 'é😀' in raw.decode() and hashlib.sha256(raw).hexdigest()==w.payload_sha256

@pytest.mark.parametrize('mutation', ['missing','duplicate','domain','field','hash','version','mapping','foreign','staleunit','bool','interval','root','mixed'])
def test_hostile_witness_rejected(owned, mutation):
    stage,w,owner = owned; o=w.origins[0]
    ws=(w,)
    if mutation=='missing': ws=()
    elif mutation=='duplicate': ws=(w,w)
    elif mutation=='domain': ws=(dataclasses.replace(w,key='["Foreign"]'),)
    elif mutation=='field': ws=(dataclasses.replace(w,field='classes'),)
    elif mutation=='hash': ws=(dataclasses.replace(w,payload_sha256='f'*64),)
    elif mutation=='version': ws=(dataclasses.replace(w,version='source-owner-witness/99'),)
    elif mutation=='mapping': ws=(dataclasses.replace(w,mapping='proven'),)
    elif mutation=='foreign': ws=(dataclasses.replace(w,origins=(dataclasses.replace(o,unit='u:'+'a'*64),)),)
    elif mutation=='staleunit': ws=(dataclasses.replace(w,origins=(dataclasses.replace(o,source_sha256='a'*64),)),)
    elif mutation=='bool': ws=(dataclasses.replace(w,origins=(dataclasses.replace(o,start=True),)),)
    elif mutation=='interval': ws=(dataclasses.replace(w,origins=(dataclasses.replace(o,end=o.end-1),)),)
    elif mutation=='root': ws=(dataclasses.replace(w,origins=(dataclasses.replace(o,native_region='r0'),)),)
    elif mutation=='mixed': ws=(dataclasses.replace(w,origins=(o,dataclasses.replace(o,native_region='r0'))),)
    with pytest.raises(ValueError):check_witnesses(ws,(owner,),stage.syntax)


def test_mixed_merge_retained_as_unsupported(tmp_path):
    p=provider();path=tmp_path/'merge.html'
    path.write_text('<html><body><script>function Avatar(){return <b>A</b>}</script><script>function Avatar(){return <b>B</b>} function MainPage(){return <Avatar/>}</script></body></html>')
    stage=BindingStage(PrototypeDocument.read(path),BindingBuildOptions(p.node,p.toolchain,p.fingerprint));stage.capture('merge')
    result=asyncio.run(stage.capture_general(concurrency=2));avatar=next(c for c in result.components if c.name=='Avatar')
    assert 'Variant 1/2' in avatar.source_code and avatar.source_owner.mapping=='unsupported-derivation'
    assert len(avatar.source_owner.origins)==2
    assert dataclasses.replace(avatar,occurrence=2).source_owner is avatar.source_owner


def test_native_build_close_reopen_and_every_call_mutation(tmp_path):
    from design_graph.model.graph.reader import GraphReader
    from design_graph.model.graph.source_build_ownership import (
        load_source_build_ownership,
    )
    from tests.unit.pipeline.test_binding_cli import build
    from tests.unit.pipeline.test_binding_cli_controls import open_db
    path=tmp_path/'build.html';path.write_text('<html><body><script>function Avatar(){return <b>😀</b>} function MainPage(){return <Avatar/>}</script></body></html>');db=tmp_path/'fresh.db'
    result=build(path,db);assert result.returncode==0,result.stderr
    database,connection=open_db(db)
    try:
        reader=GraphReader(connection,Path(str(db)+'.state.json'));receipt=load_source_build_ownership(reader)
        w=next(w for w in receipt.witnesses if w.key=='["Avatar"]' and w.table=='Component');assert w.mapping=='exact-slice'
        connection.execute("MATCH (n:Component {name:'Avatar'}) SET n.source_code='changed'").close()
        with pytest.raises(ValueError):load_source_build_ownership(reader)
    finally:connection.close();database.close()


@pytest.mark.parametrize('mutation', ['legacy', 'bool', 'hash', 'extra', 'foreign-shared'])
def test_persisted_owner_envelope_rejected_after_reopen(tmp_path, mutation):
    from design_graph.model.graph.reader import GraphReader
    from design_graph.model.graph.source_build_ownership import (
        load_source_build_ownership,
    )
    from tests.unit.pipeline.test_binding_cli import build
    from tests.unit.pipeline.test_binding_cli_controls import open_db
    path = tmp_path / 'shared.html'
    path.write_text('<html><body><script>function Avatar(){return <b>shared</b>} function MainPage(){return <Avatar/>}</script></body></html>')
    db = tmp_path / 'owned.db'
    assert build(path, db).returncode == 0
    seal = Path(str(db) + '.binding.json')
    manifest = json.loads(seal.read_text())
    anchor = manifest['ownership']
    database, connection = open_db(db)
    try:
        payload = connection.execute('MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id RETURN s.payload', {'id': anchor['snapshot']}).get_all()[0][0]
        data = json.loads(payload)
        witness = next(w for w in data['witnesses'] if w['mapping'] == 'exact-slice')
        if mutation == 'legacy':
            data['version'] = 'source-build-ownership/1'
        elif mutation == 'bool':
            witness['origins'][0]['start'] = True
        elif mutation == 'hash':
            witness['payload_sha256'] = 'f' * 64
        elif mutation == 'extra':
            witness['trusted'] = True
        else:
            # Identical function bytes do not confer a foreign qualified unit.
            witness['origins'][0]['unit'] = 'u:' + 'f' * 64
        changed = json.dumps(data)
        connection.execute('MATCH (s:BindingContextSnapshot) WHERE s.snapshot_id=$id SET s.payload=$payload', {'id': anchor['snapshot'], 'payload': changed}).close()
        # Even a coherently rehashed retained anchor cannot bypass typed/semantic
        # admission. This is consistency checking, not authentication.
        manifest['ownership']['sha256'] = hashlib.sha256(changed.encode()).hexdigest()
        seal.write_text(json.dumps(manifest))
    finally:
        connection.close(); database.close()
    database, connection = open_db(db)
    try:
        reader = GraphReader(connection, Path(str(db) + '.state.json'))
        with pytest.raises(ValueError):
            load_source_build_ownership(reader)
    finally:
        connection.close(); database.close()
