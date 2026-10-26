"""Explicit inputs only; no historic selection heuristic or product transplant."""
from pathlib import Path
import json
import shutil
import subprocess
import time
import sys
from .common import digest, fresh, write_json
from .gates import disjoint, safe_hashes
from .oracle import capture


def graph_ready(graph, targets):
    import kuzu
    from design_graph.model.graph.reader import GraphReader
    db = kuzu.Database(str(graph),read_only=True); conn = kuzu.Connection(db)
    try:
        reader = GraphReader(conn); records=[]
        for target in targets:
            source = reader.get_full_source(target['component'])
            screen = reader.get_screen(target['component'])
            component = reader.get_component_spec(target['component'])
            if not source or not source.get('source_code','').strip() or not (screen or component):
                raise ValueError('target absent from integral graph')
            records.append({'component':target['component'],'source_chars':len(source['source_code']),
                            'kind':'screen' if screen else 'component'})
        return {'ready':True,'targets':records,'graph_sha256':digest(graph),
                'scope':'setup only; never native session MCP evidence'}
    finally: conn.close(); db.close()


def prepare(root, source, plan_path, targets_path, graph=None):
    root, source = Path(root), Path(source)
    prep = fresh(root/'preparation'); agent=fresh(prep/'agent-input')
    oracle_root = prep/'oracle'
    disjoint(agent,oracle_root,root/'sessions')
    plans = json.loads(Path(plan_path).read_text()); targets=json.loads(Path(targets_path).read_text())
    if len(targets)!=3 or set(plans)!= {'1','2','3'}:
        raise ValueError('three explicit targets and private oracle plans required')
    # Only semantic target declarations are shared; no prepared selectors/offsets.
    if any(set(t) != {'title','state','component','key','label'} for t in targets):
        raise ValueError('target declaration fields differ')
    input_dir=fresh(agent/'input'); shutil.copyfile(source,input_dir/'original.html')
    write_json(prep/'targets.private.json',targets)
    write_json(prep/'functional-plan.private.json',plans)
    capture(source,oracle_root,plans)
    started=time.monotonic()
    graph=Path(graph) if graph else fresh(root/'graph')/'original.db'
    reused_index = graph.is_file()
    if not reused_index:
        argv=[str(Path(sys.executable).parent/'design-graph'),str(source),'--db',str(graph)]
        with (prep/'index.log').open('x') as log:
            result=subprocess.run(argv,stdout=log,stderr=subprocess.STDOUT,timeout=900)
        if result.returncode: raise ValueError('integral index failed; stop')
    index_seconds = None if reused_index else time.monotonic()-started
    readiness_started=time.monotonic()
    write_json(prep/'readiness.private.json',graph_ready(graph,targets))
    readiness_seconds=time.monotonic()-readiness_started
    write_json(prep/'setup.private.json',{'source_sha256':digest(source),'source_bytes':source.stat().st_size,
        'graph':str(graph),'index_seconds':index_seconds,'reused_setup_index':reused_index,
        'readiness_seconds':readiness_seconds,
        'inputs':safe_hashes(agent),'source_read_only':True})
    return prep
