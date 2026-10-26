#!/usr/bin/env python3
"""Static benchmark matrix at the Pages prefix; never runs measured agents."""
import argparse
import hashlib
import json
import threading
import time
from pathlib import Path

from preview import ROOT, PREFIX, server
from test_benchmark import HASHES, check_metrics
from test_browser import CONTRAST, measure_contrast


def run(output):
    from playwright.sync_api import sync_playwright, expect
    output.mkdir(parents=True, exist_ok=True)
    data=json.loads((ROOT/'site/benchmark-ipede-v2/data.json').read_text())
    report={'matrix': [], 'unavailableBrowsers': []}
    with server(0) as httpd:
        thread=threading.Thread(target=httpd.serve_forever,daemon=True); thread.start()
        url=f'http://127.0.0.1:{httpd.server_port}{PREFIX}'
        try:
            with sync_playwright() as pw:
                for name in ('chromium','firefox'):
                    engine=getattr(pw,name)
                    if not Path(engine.executable_path).is_file():
                        if name == 'chromium': raise RuntimeError('Chromium required')
                        report['unavailableBrowsers'].append(name); continue
                    browser=engine.launch()
                    try:
                        for js in (True,False):
                            for theme in (('dark','light') if js else ('dark',)):
                                for width,height in ((1280,900),(390,844)):
                                    ctx=browser.new_context(java_script_enabled=js,viewport={'width':width,'height':height},accept_downloads=True)
                                    try:
                                        if theme == 'light':
                                            ctx.add_init_script("localStorage.setItem('design-graph-theme','light')")
                                        errors=[]; requests=[]; console=[]
                                        page=ctx.new_page()
                                        page.on('pageerror',lambda e: errors.append(str(e)))
                                        page.on('console',lambda m: console.append(m.text))
                                        page.on('requestfailed',lambda r: errors.append(r.url))
                                        page.on('request',lambda r: requests.append(r.url))
                                        page.goto(url)
                                        expect(page.locator('html')).to_have_attribute('data-theme',theme)
                                        page.get_by_role('link',name='Benchmarks',exact=True).click()
                                        expect(page.locator('#benchmarks h2')).to_be_in_viewport()
                                        section=page.locator('#benchmarks')
                                        expect(section).to_contain_text('Causal effect NOT IDENTIFIED')
                                        assert section.locator('table').count()==3
                                        assert section.locator('caption').count()==3
                                        assert section.locator('table').nth(1).locator('tbody tr').count()==3
                                        assert section.locator('table').nth(2).locator('tbody tr').count()==6
                                        tags=section.locator('[data-source]').evaluate_all('els => els.map(el => [el.tagName, Object.fromEntries(Array.from(el.attributes, a => [a.name,a.value]))])')
                                        check_metrics(tags,data)
                                        for el in section.locator('[data-source]').all():
                                            value=json.loads(el.get_attribute('data-value'))
                                            shown='Unavailable' if value is None else format(value,el.get_attribute('data-format') or '')
                                            expect(el).to_have_text(shown)
                                        assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')
                                        assert section.locator('table').evaluate_all('els => els.every(el => el.scrollWidth <= el.clientWidth + 1)')
                                        if js:
                                            contrast=measure_contrast(page)
                                        else:
                                            # Disabled page scripts also disable requestAnimationFrame
                                            # callbacks in the async stability helper. Poll rendered
                                            # animations from the driver, then measure once.
                                            page.mouse.move(-1,-1)
                                            deadline=time.monotonic()+5
                                            while page.evaluate("document.getAnimations().some(a => a.pending || a.playState === 'running')"):
                                                if time.monotonic()>deadline: raise AssertionError('No-JS styles did not settle')
                                                time.sleep(.02)
                                            contrast=page.evaluate(CONTRAST)
                                        assert not contrast['failures'],contrast
                                        assert section.locator('.benchmark-mae [data-value]').evaluate_all('''els => els.every(el => {
                                            const range=document.createRange(); range.selectNodeContents(el);
                                            return range.getClientRects().length === 1;
                                        })''')
                                        for filename,digest in HASHES.items():
                                            link=section.locator(f'a[href="benchmark-ipede-v2/{filename}"]')
                                            with page.expect_download() as event: link.click()
                                            download=event.value
                                            assert download.suggested_filename==filename
                                            assert hashlib.sha256(Path(download.path()).read_bytes()).hexdigest()==digest
                                        assert not errors and not console,(errors,console)
                                        assert all(r.startswith(url) for r in requests),requests
                                        key=f'{name}-{theme}-{width}-js{js}'
                                        section.screenshot(path=str(output/f'{key}.png'))
                                        report['matrix'].append({'case':key,'browserVersion':browser.version,'metrics':len(tags),'tables':3,'downloads':2,'contrast':contrast,'errors':errors,'externalRequests':0})
                                        print('PASS',key,flush=True)
                                    finally: ctx.close()
                    finally: browser.close()
        finally:
            httpd.shutdown(); thread.join()
            (output/'benchmark-browser-report.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'.venv/benchmark-browser-evidence')
    args=parser.parse_args(); destination=args.output.resolve()
    if not destination.is_relative_to(ROOT) or destination.is_relative_to(ROOT/'site'):
        parser.error('Keep evidence inside this worktree and outside site/.')
    run(destination)
