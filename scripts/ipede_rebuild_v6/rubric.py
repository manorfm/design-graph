"""Freeze private assertions from existing real oracle; never evaluate generation here."""
import json
import hashlib
from pathlib import Path
import jsonschema
from .common import digest, write_json

VIEWPORTS = ['1280x900', '390x844']
VISUAL = {
    'geometry': 'Compare all shell, main panel, table/card/dialog bounding edges to reference: maximum 4 CSS px desktop, 3 mobile; preserve observed overflow.',
    'typography': 'All visible reference text, line wraps, font size (within 1 CSS px), weight and alignment match; no replacement content.',
    'palette': 'All visible foreground/background/border colors within 8 per RGB channel; no missing surface.',
    'controls': 'Reference controls, icons, borders, selected/disabled states and spacing within geometry tolerance; no omitted control.',
    'content': 'All visible rows, columns, cards, labels, values and images match reference; no screenshot-as-page.'}
CRITICAL = ['wrong_target','blank_output','missing_required_state','invented_backend',
            'copied_implementation','prohibited_generation','unreviewed_access',
            'unusable_primary_action','budget_exceeded']
THRESHOLDS = {'visual':0.9, 'functional':1.0, 'usability':1.0, 'equivalence_margin':0.0}


def negative_hash(check):
    negative = check.get('inherited_negative')
    return None if negative is None else hashlib.sha256(json.dumps(negative, sort_keys=True).encode()).hexdigest()


def build(preparation, assignments):
    """assignments: private oracle group -> target number. Only existing bytes read."""
    preparation = Path(preparation)
    rows = []
    for group, mapping in assignments.items():
        receipt = json.loads((preparation/group/'receipt.json').read_text())
        if receipt.get('passed') is not True:
            raise ValueError('real successful oracle required')
        for key, page in mapping.items():
            plan = receipt['plans'][key]
            for vp in VIEWPORTS:
                folder = preparation/group/f'{key}-{vp}'
                checks = {'visual':[], 'functional':[], 'usability':[]}
                for step in range(len(plan['steps'])+1):
                    stem = folder/f'{step:02}'
                    dom = stem.with_suffix('.json'); png = stem.with_suffix('.png')
                    observed = json.loads(dom.read_text())
                    base = f'{group}:{key}:{vp}:{step:02}'
                    ref = {'dom':dom.relative_to(preparation).as_posix(), 'dom_sha256':digest(dom),
                           'image':png.relative_to(preparation).as_posix(), 'image_sha256':digest(png)}
                    checks['functional'].append({'id':base+':state','reference':ref,
                        'action':None if step==0 else plan['steps'][step-1],
                        'assert':{'text':observed['text'],'controls':observed['controls']},
                        'rule':'After frozen entry and preceding actions, exact normalized text and ordered controls (tag,text,placeholder,type,value,disabled,visible) equal oracle; no backend; inert action must preserve DOM and emit no download/network.'})
                    for dimension, rule in VISUAL.items():
                        checks['visual'].append({'id':base+':'+dimension,'reference':ref,'rule':rule})
                    for dimension, rule in {
                        'reachability':'Every primary control for this state is reachable by pointer and keyboard at this viewport without inaccessible clipping.',
                        'legibility':'No content or actionable label is lost to clipping/overlap; readable text and sufficient visible controls. Assess absolute usability independently of fidelity.'}.items():
                        checks['usability'].append({'id':base+':'+dimension,'reference':ref,'rule':rule})
                rows.append({'page':page,'viewport':vp,'group':group,'key':key,'entry':plan['entry'],'checks':checks})
    result = {'version':1,'thresholds':THRESHOLDS,'critical_failures':CRITICAL,'rows':rows,
              'original_negatives':[],
              'scoring':'Boolean checks only; fixed denominators, missing check = unknown (null), never pass or zero. Each viewport independently requires visual .9, functional 1, reference usability 1 for acceptance; absolute usability threshold 1 is reported separately. Critical failure forbids equivalence. Human evidence and exact frozen-negative/no-regression review required.'}
    validate(result)
    return result


def validate(rubric):
    schema = json.loads(Path(__file__).with_name('rubric.schema.json').read_text())
    jsonschema.validate(rubric,schema)
    seen=set()
    for row in rubric['rows']:
        for checks in row['checks'].values():
            for check in checks:
                if check['id'] in seen: raise ValueError('duplicate rubric check')
                seen.add(check['id'])
                if 'inherited_negative' in check:
                    if checks is not row['checks']['usability']:
                        raise ValueError('negative must belong to a usability check')
                    if check['inherited_negative']['reference'] != check['reference']:
                        raise ValueError('negative must bind exact check/state reference')
    if {(r['page'],r['viewport']) for r in rubric['rows']} != {(p,v) for p in [1,2,3] for v in VIEWPORTS}:
        raise ValueError('all target/viewports required')


def public(rubric):
    validate(rubric)
    return {'version':1, 'thresholds':rubric['thresholds'],
            'denominators':[{'page':p,'viewport':v, **{kind:sum(len(r['checks'][kind]) for r in rubric['rows'] if r['page']==p and r['viewport']==v) for kind in ['visual','functional','usability']}} for p in [1,2,3] for v in VIEWPORTS]}


def verify_references(preparation, rubric):
    validate(rubric)
    preparation=Path(preparation).resolve()
    for row in rubric['rows']:
        for checks in row['checks'].values():
            for check in checks:
                ref=check['reference']
                for kind in ['dom','image']:
                    path=(preparation/ref[kind]).resolve()
                    if not path.is_relative_to(preparation) or digest(path)!=ref[kind+'_sha256']:
                        raise ValueError('rubric reference changed or outside preparation')
                if 'assert' in check and check['assert']!=json.loads((preparation/ref['dom']).read_text()):
                    raise ValueError('rubric assertion differs from real DOM')
