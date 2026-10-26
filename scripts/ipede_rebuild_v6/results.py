"""Downstream materialization from real session metrics and private human evaluation.

No generation, reconstruction, evaluation, tariffs or missing-value imputation.
"""
import json
from pathlib import Path
import jsonschema
from .common import digest, fresh, write_json
from .gates import public_document
from .protocol import ORDER
from .rubric import VIEWPORTS, public, validate

RESOURCE = ['input_tokens','cached_input_tokens','output_tokens','generation_seconds','operations']
COMPARE = RESOURCE + ['evaluation_seconds','supervision_seconds','money']
KINDS = ['visual','functional','usability']
DECISIONS = ['economizou mantendo qualidade','melhorou qualidade com custo adicional','não trouxe ganho','inconclusivo']


def delta(a,b):
    return {'absolute':None if a is None or b is None else b-a,
            'percent':None if a in (None,0) or b is None else 100*(b-a)/a}


def load(path):
    return json.loads(path.read_text()) if path.is_file() else None


def quality_schema(rubric, page):
    rows=[]
    for vp in VIEWPORTS:
        ids=[c['id'] for r in rubric['rows'] if r['page']==page and r['viewport']==vp for cs in r['checks'].values() for c in cs]
        rows.append({'type':'object','additionalProperties':False,'required':['viewport','checks','critical_failures'],
                     'properties':{'viewport':{'const':vp},'checks':{'type':'object','additionalProperties':False,'required':ids,'properties':{i:{'type':['boolean','null']} for i in ids}},
                                   'critical_failures':{'type':'array','uniqueItems':True,'items':{'enum':rubric['critical_failures']}}}})
    return {'type':'object','additionalProperties':False,
            'required':['freeze_sha256','rubric_sha256','output_sha256','events_sha256','metrics_sha256','reviewer','reviewed_at','trace_review','access_review','independence_review','evaluation_seconds','rows'],
            'properties':{**{k:{'type':'string','pattern':'^[0-9a-f]{64}$'} for k in ['freeze_sha256','rubric_sha256','output_sha256','events_sha256','metrics_sha256']},
                          **{k:{'type':'string','minLength':1} for k in ['reviewer','reviewed_at']},
                          **{k:{'type':'boolean'} for k in ['trace_review','access_review','independence_review']},
                          'evaluation_seconds':{'type':['number','null'],'minimum':0},
                          'rows':{'type':'array','minItems':2,'maxItems':2,'prefixItems':rows,'items':False}}}


def evaluate(rubric,page,evaluation):
    if evaluation is not None: jsonschema.validate(evaluation,quality_schema(rubric,page))
    scores=[]
    for index,vp in enumerate(VIEWPORTS):
        row={'viewport':vp,'critical_failures':None if evaluation is None else evaluation['rows'][index]['critical_failures']}
        for kind in KINDS:
            ids=[c['id'] for r in rubric['rows'] if r['page']==page and r['viewport']==vp for c in r['checks'][kind]]
            values=[evaluation['rows'][index]['checks'][i] for i in ids] if evaluation is not None else [None]*len(ids)
            complete=all(v is not None for v in values)
            passed=sum(v is True for v in values) if complete else None
            row[kind]={'denominator':len(ids),'passed':passed,'score':None if passed is None else passed/len(ids)}
        scores.append(row)
    return scores


def accepted(quality, evaluation, rubric):
    if evaluation is None: return None
    if not all(evaluation[k] for k in ['trace_review','access_review','independence_review']): return False
    if any(r['critical_failures'] for r in quality): return False
    if any(r[k]['score'] is None for r in quality for k in KINDS): return None
    return all(r[k]['score']>=rubric['thresholds'][k] for r in quality for k in KINDS)


def conclusion(a,b):
    # MCP adherence is not a quality dimension. Cache is a subset, never added.
    if any(s['metrics']['accepted'] is not True or s['metrics']['valid'] is not True for s in [a,b]): return 'inconclusivo'
    if any(s['metrics'][k] is None for s in [a,b] for k in RESOURCE): return 'inconclusivo'
    aq=[r[k]['score'] for r in a['quality'] for k in KINDS]
    bq=[r[k]['score'] for r in b['quality'] for k in KINDS]
    if any(v is None for v in aq+bq): return 'inconclusivo'
    # Cache is reported, but not optimized: a higher cache hit count is not a cost.
    costs=[k for k in RESOURCE if k!='cached_input_tokens']
    av=[a['metrics'][k] for k in costs];bv=[b['metrics'][k] for k in costs]
    q_ge=all(y>=x for x,y in zip(aq,bq));q_le=all(y<=x for x,y in zip(aq,bq))
    c_le=all(y<=x for x,y in zip(av,bv));c_ge=all(y>=x for x,y in zip(av,bv))
    if q_ge and c_le and av!=bv: return DECISIONS[0]
    if q_ge and aq!=bq and c_ge and av!=bv: return DECISIONS[1]
    if q_ge and aq!=bq and av==bv: return 'inconclusivo'  # quality gain without additional cost: explicit trade category limitation
    if q_le and c_ge: return DECISIONS[2]
    return DECISIONS[3]


def materialize(root, destination):
    root=Path(root);destination=Path(destination)
    rubric_path=root/'preparation/rubric.private.json';rubric=load(rubric_path);validate(rubric)
    data=load(Path(__file__).with_name('data.json'))
    data['rubric']=public(rubric)
    data['freeze_sha256']=digest(root/'freeze.json') if (root/'freeze.json').is_file() else None
    any_metrics=False
    for session,(page,lane) in zip(data['sessions'],ORDER):
        base=root/f'sessions/{page}-{lane}';proof=base/'evidence'
        raw=load(proof/'metrics.json');evaluation=load(proof/'evaluation.private.json')
        if evaluation is not None:
            jsonschema.validate(evaluation,quality_schema(rubric,page))
            bindings={'freeze_sha256':root/'freeze.json','rubric_sha256':rubric_path,'output_sha256':base/'work/output/page.html','events_sha256':proof/'events.jsonl','metrics_sha256':proof/'metrics.json'}
            if any(evaluation[k]!=digest(path) for k,path in bindings.items()): raise ValueError('evaluation evidence binding changed')
        m=session['metrics']
        if raw is not None:
            any_metrics=True
            for k in ['input_tokens','cached_input_tokens','output_tokens']:m[k]=(raw.get('usage') or {}).get(k)
            for k,source in {'generation_seconds':'seconds','supervision_seconds':'supervision_seconds','operations':'tool_calls','operations_by_type':'operations_by_type','effective_context':'effective_context','fallback':'fallback'}.items():m[k]=raw.get(source)
            # No verifiable tariff supported: money stays null.
            m['errors']=None if raw.get('errors') is None else [{'id':e.get('id'),'type':e.get('type'),'exit_code':e.get('exit_code')} for e in raw['errors']]
            m['checkpoints']=len(list((proof/'checkpoints').glob('*.bin'))) if (proof/'checkpoints').is_dir() else None
            m['provenance']={'metrics_sha256':digest(proof/'metrics.json')}
            m['valid']=None if 'stop_reason' not in raw or 'exit_code' not in raw else raw['stop_reason'] is None and raw['exit_code']==0
            if m['operations'] is not None and m['operations']>120:m['valid']=False
            if m['generation_seconds'] is not None and m['generation_seconds']>900:m['valid']=False
            if lane=='B':
                from .preflight import evidence
                if (proof/'transcript.jsonl').is_file():
                    try:evidence(proof,require_usage=True);m['mcp']={'adherent':raw.get('queried_screen_indexes')==[1]}
                    except (OSError,ValueError,KeyError,TypeError):m['mcp']={'adherent':False}
                    if m['mcp']['adherent'] is not True:m['valid']=False
                else:m['valid']=None
            # Automated gates plus private human review are both mandatory.
            if (proof/'events.jsonl').is_file() and (base/'work/output/page.html').is_file():
                from .audit import trace_gate,copy_scan
                try:
                    events=[json.loads(x) for x in (proof/'events.jsonl').read_text().splitlines()]
                    trace_gate(events,lane,base/'work')
                    from .runner import completed_usage
                    actual=completed_usage(events)
                    if any(m[k] is not None and m[k]!=actual[k] for k in actual):m['valid']=False
                    copy_scan(base/'work/input/original.html',base/'work/output/page.html')
                except (OSError,ValueError):m['valid']=False
            else:m['valid']=None if m['valid'] else m['valid']
        session['quality']=evaluate(rubric,page,evaluation)
        m['accepted']=accepted(session['quality'],evaluation,rubric)
        if m['valid'] is not True and m['accepted'] is True:m['accepted']=False
        m['evaluation_seconds']=None if evaluation is None else evaluation['evaluation_seconds']
    data['status']='collected' if any_metrics else 'not_collected'
    data['approval']='pending'  # approval is never inferred from output files
    source=root/'preparation/agent-input/input/original.html'
    data['source_sha256']=digest(source) if source.is_file() else None
    frozen=load(root/'freeze.json')
    data['identity_sha256']=None if frozen is None else frozen.get('identity',{}).get('sha256')
    data['comparisons']=[]
    for page in [1,2,3]:
        a=next(s for s in data['sessions'] if s['page']==page and s['lane']=='A')
        b=next(s for s in data['sessions'] if s['page']==page and s['lane']=='B')
        data['comparisons'].append({'page':page,'deltas':{k:delta(a['metrics'][k],b['metrics'][k]) for k in COMPARE},'conclusion':conclusion(a,b)})
    data['totals']={k:None if any(s['metrics'][k] is None for s in data['sessions']) else sum(s['metrics'][k] for s in data['sessions']) for k in COMPARE}
    setup=load(root/'preparation/setup.private.json')
    data['setup_seconds']=None if setup is None else setup.get('index_seconds')
    data['total_generation_with_setup_seconds']=None if data['totals']['generation_seconds'] is None or data['setup_seconds'] is None else data['totals']['generation_seconds']+data['setup_seconds']
    data['lane_totals']={lane:{k:None if any(s['metrics'][k] is None for s in data['sessions'] if s['lane']==lane) else sum(s['metrics'][k] for s in data['sessions'] if s['lane']==lane) for k in COMPARE} for lane in ['A','B']}
    data['overall_deltas']={k:delta(data['lane_totals']['A'][k],data['lane_totals']['B'][k]) for k in COMPARE}
    a_seconds=data['lane_totals']['A']['generation_seconds'];b_seconds=data['lane_totals']['B']['generation_seconds']
    b_setup=None if b_seconds is None or data['setup_seconds'] is None else b_seconds+data['setup_seconds']
    data['setup_comparison']={'A_generation_seconds':a_seconds,'B_generation_plus_setup_seconds':b_setup,'delta':delta(a_seconds,b_setup)}
    validate_data(data)
    public_document(data);fresh(destination);write_json(destination/'data.json',data)
    fmt=lambda value:json.dumps(value,ensure_ascii=False)
    lines=['# Estudo de caso — n=1 por alvo','',
           'Cache é subconjunto da entrada. Delta=B−A; percentual=100×(B−A)/A; A=0/null => percentual null.',
           'Setup separado, sem rateio. Dinheiro indisponível=null. MCP é aderência, sem crédito de qualidade.', '']
    for row in data['comparisons']:
        pair={s['lane']:s for s in data['sessions'] if s['page']==row['page']}
        lines.extend([f"Alvo {row['page']}: {row['conclusion']}.",'',
                      '| Métrica | A | B | B−A | 100×(B−A)/A |','|---|---:|---:|---:|---:|'])
        lines.extend(f"| {k} | {fmt(pair['A']['metrics'][k])} | {fmt(pair['B']['metrics'][k])} | {fmt(v['absolute'])} | {fmt(v['percent'])} |" for k,v in row['deltas'].items())
        lines.extend(['','| Lane / viewport | Visual pass/denom | Funcional pass/denom | Usabilidade pass/denom | Falhas críticas |','|---|---:|---:|---:|---|'])
        for lane,session in pair.items():
            for q in session['quality']:
                cells=[f"{fmt(q[k]['passed'])}/{q[k]['denominator']}" for k in KINDS]
                lines.append(f"| {lane} / {q['viewport']} | "+' | '.join(cells)+f" | {fmt(q['critical_failures'])} |")
        lines.append('')
    lines.extend(['Totais das seis sessões (qualquer parcela ausente => null):', '',
                  '| Métrica | Total |','|---|---:|'])
    lines.extend(f"| {k} | {fmt(v)} |" for k,v in data['totals'].items())
    lines.extend(['', f"Setup de indexação (s): {fmt(data['setup_seconds'])}.",
                  f"Total geração + setup (s): {fmt(data['total_generation_with_setup_seconds'])}.",
                  'Preflight neutro excluído dos totais medidos.', ''])
    lines.extend(['| Métrica agregada | A (3 sessões) | B (3 sessões) | B−A | % |','|---|---:|---:|---:|---:|'])
    lines.extend(f"| {k} | {fmt(data['lane_totals']['A'][k])} | {fmt(data['lane_totals']['B'][k])} | {fmt(data['overall_deltas'][k]['absolute'])} | {fmt(data['overall_deltas'][k]['percent'])} |" for k in COMPARE)
    lines.extend(['', 'Comparação de geração com indexação B uma vez, sem rateio: '+fmt(data['setup_comparison']), ''])
    lines.extend(data['limitations']);text='\n'.join(lines)+'\n';public_document(text);(destination/'report.md').write_text(text)
    return data


def validate_data(data):
    """Schema plus arithmetic invariants JSON Schema cannot express."""
    jsonschema.validate(data,load(Path(__file__).with_name('data.schema.json')))
    for s in data['sessions']:
        m=s['metrics']
        if m['cached_input_tokens'] is not None and m['input_tokens'] is not None and m['cached_input_tokens']>m['input_tokens']:
            raise ValueError('cache exceeds input')
        for row in s['quality']:
            for k in KINDS:
                v=row[k]
                if v['score'] != (None if v['passed'] is None else v['passed']/v['denominator']):
                    raise ValueError('score arithmetic mismatch')
    for row in data['comparisons']:
        a=next(s for s in data['sessions'] if s['page']==row['page'] and s['lane']=='A')
        b=next(s for s in data['sessions'] if s['page']==row['page'] and s['lane']=='B')
        if row['deltas']!={k:delta(a['metrics'][k],b['metrics'][k]) for k in COMPARE} or row['conclusion']!=conclusion(a,b):
            raise ValueError('comparison arithmetic/decision mismatch')

    for k in COMPARE:
        values=[s['metrics'][k] for s in data['sessions']]
        expected=None if any(v is None for v in values) else sum(values)
        if data['totals'][k]!=expected:raise ValueError('total arithmetic mismatch')
    total=data['totals']['generation_seconds'];setup=data['setup_seconds']
    if data['total_generation_with_setup_seconds']!=(None if total is None or setup is None else total+setup):
        raise ValueError('setup total mismatch')

    for lane in ['A','B']:
        for k in COMPARE:
            values=[s['metrics'][k] for s in data['sessions'] if s['lane']==lane]
            if data['lane_totals'][lane][k]!=(None if any(v is None for v in values) else sum(values)):
                raise ValueError('lane total mismatch')
    if data['overall_deltas']!={k:delta(data['lane_totals']['A'][k],data['lane_totals']['B'][k]) for k in COMPARE}:
        raise ValueError('overall delta mismatch')
    a=data['lane_totals']['A']['generation_seconds'];b=data['lane_totals']['B']['generation_seconds']
    adjusted=None if b is None or setup is None else b+setup
    if data['setup_comparison']!={'A_generation_seconds':a,'B_generation_plus_setup_seconds':adjusted,'delta':delta(a,adjusted)}:
        raise ValueError('setup comparison mismatch')
