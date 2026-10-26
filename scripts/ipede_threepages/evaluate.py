from __future__ import annotations
import json
import time
from pathlib import Path
from .browser import capture
from .common import fresh, verify, write_json


def evaluate(root):
    prep=root/'preparation';verify(prep)
    plan=json.loads((prep/'functional-plan.private.json').read_text())
    runtime=json.loads((prep/'environment.json').read_text())
    out=fresh(root/'evaluation')
    results=[]
    for i, selected in enumerate(json.loads((prep/'selection.json').read_text()),1):
        for lane in ['original','A','B']:
            destination=out/f'{lane}-page-{i}'
            source=prep/'original.html' if lane=='original' else root/'runs'/lane/'work'/'output'/f'page-{i}.html'
            if not source.is_file():
                destination.mkdir();write_json(destination/'missing.json',dict(missing=True));continue
            capture(source,destination,runtime['browser'],
                entry=plan[str(i)]['entry'] if lane=='original' else [],tests=plan[str(i)]['tests'])
        for viewport in ['1280x900','390x844']:
            from PIL import Image, ImageDraw, ImageChops, ImageStat
            width,height=map(int,viewport.split('x'))
            comparison=Image.new('RGB',(width*3,height+30),'#222222');draw=ImageDraw.Draw(comparison)
            reference=out/f'original-page-{i}'/(viewport+'.png')
            for column,lane in enumerate(['original','A','B']):
                path=out/f'{lane}-page-{i}'/(viewport+'.png')
                draw.text((column*width+5,8),f'{lane} / page {i} / {viewport}',fill='white')
                if path.exists(): comparison.paste(Image.open(path).convert('RGB'),(column*width,30))
                if lane!='original':
                    functional=out/f'{lane}-page-{i}'/(viewport+'.functional.json')
                    logs=out/f'{lane}-page-{i}'/(viewport+'.logs.json')
                    score=None
                    if path.exists() and reference.exists():
                        diff=ImageChops.difference(Image.open(reference).convert('RGB'),Image.open(path).convert('RGB'))
                        score=sum(ImageStat.Stat(diff).mean)/3/255
                    results.append(dict(lane=lane,page=i,viewport=viewport,
                        functional_passed=json.loads(functional.read_text())['passed'] if functional.exists() else False,
                        browser_errors=len(json.loads(logs.read_text()).get('errors',[])) if logs.exists() else None,
                        diagnostic_rgb_mae_fraction=score,visual_review='pending',accepted=None,
                        accepted_seconds=None,artifact_timing_distinct=True))
            comparison.save(out/f'comparison-page-{i}-{viewport}.png')
    write_json(root/'evaluation-results.private.json',results)
    return results
