from __future__ import annotations
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from .common import digest, fresh, hashes, write_json
from .inventory import decode, route_inventory


def prepare(root, source, browser, functional_plan):
    out = fresh(root/'preparation')
    started = time.monotonic()
    shutil.copyfile(source, out/'original.html')
    bundle, resources, modules = decode(source, out/'input')
    inventory = route_inventory(modules)
    write_json(out/'inventory.private.json', inventory)
    write_json(out/'selection.json', inventory['selection'])
    plan = json.loads(Path(functional_plan).read_text())
    if set(plan) != {'1','2','3'} or any(not p.get('tests') for p in plan.values()):
        raise ValueError('three nonempty evaluator-only functional plans required')
    write_json(out/'functional-plan.private.json', plan)
    prompt = '''Build THREE DIFFERENT executable HTML pages from input/, reproducing each selected route in selection.json at its frozen default state. Write page-1.html, page-2.html, page-3.html in output/ in selection order. Reconstruct each page and its relevant interactions; do not copy, embed, iframe, or bootstrap the whole application. Retain the relevant shared shell. Use the supplied source and resources only; no network, web, apps, other agents, earlier runs, evaluator files, original rendered DOM or screenshots. Work only in this work directory. MCP tools, if available, may be used; common input files are an allowed fallback. Do not inspect parent directories, auth/config files, or other work directories. Do not install dependencies. Output must work offline with local assets, data or blob URLs. Match both 1280x900 and 390x844 with fresh empty storage, pt-BR locale and America/Fortaleza timezone; fixed date 2026-10-26T12:00:00Z. Implement functional controls relevant to each page. You have 900 seconds and 90 tool calls total for all three pages. Do not self-report artifact timestamps or token splits.\n'''
    (out/'prompt.txt').write_text(prompt)
    write_json(out/'environment.json', dict(python=os.sys.executable, python_version=platform.python_version(),
        browser=str(Path(browser).resolve()), browser_exists=Path(browser).is_file(),
        codex=shutil.which('codex'), codex_version=subprocess.check_output(['codex','--version'],text=True).strip(),
        worktree=str(Path.cwd()), revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        executables={name:shutil.which(name) for name in ['python','pytest','design-mcp','design-graph']},
        packages={name:importlib.metadata.version(name) for name in ['playwright','pytest','beautifulsoup4','mcp','kuzu','pillow']},
        source_sha256=digest(source), source_bytes=Path(source).stat().st_size,
        decode_prepare_seconds=time.monotonic()-started, credential_contents_accessed=False,
        cache_state='OS cache uncontrolled; no measured runs started'))
    from .browser import capture
    for index in range(1,4):
        capture(out/'original.html', out/f'reference-page-{index}', browser,
                entry=plan[str(index)]['entry'], tests=plan[str(index)]['tests'])
    proof = []
    for index in range(1,4):
        for viewport in ['1280x900','390x844']:
            folder = out/f'reference-page-{index}'
            result = json.loads((folder/(viewport+'.functional.json')).read_text())
            logs = json.loads((folder/(viewport+'.logs.json')).read_text())
            proof.append(dict(page=index, viewport=viewport, passed=result['passed'],
                passed_steps=sum(step['passed'] for step in result.get('steps', [])),
                expected_steps=len(plan[str(index)]['tests']), browser_errors=len(logs['errors']),
                baseline_sha256=digest(folder/(viewport+'.png')) if (folder/(viewport+'.png')).exists() else None))
    write_json(out/'original-proof.private.json', proof)
    if any(not p['passed'] or p['browser_errors'] for p in proof):
        raise ValueError('original functional validation failed; private proof retained')
    # Public-to-agent input excludes evaluator inventory, original wrapper and preparation logs.
    agent = fresh(out/'agent-input')
    shutil.copytree(out/'input', agent/'input')
    shutil.copyfile(out/'selection.json', agent/'selection.json')
    write_json(out/'freeze.json',dict(files=hashes(out), input_hashes=hashes(agent),
        instrument_hashes={name:sha for name,sha in hashes(Path(__file__).parent).items()
                           if '__pycache__' not in Path(name).parts and not name.endswith('.pyc')},
        selection_status='parent-settled root NAV nonplaceholder policy; lower median',
        review_required=True, frozen_monotonic=time.monotonic(),
        frozen_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())))
    return out
