"""Offline fresh-context capture; evaluator-only evidence never enters agent workdirs."""
from __future__ import annotations
import contextlib
import datetime
import functools
import http.server
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from .common import fresh, write_json

DOM = """() => ({text:document.body.innerText, controls:[...document.querySelectorAll('button,input,select,textarea,a')].map(e=>{const r=e.getBoundingClientRect();return {tag:e.tagName,text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),rect:{x:r.x,y:r.y,width:r.width,height:r.height}}}), title:document.title})"""

@contextlib.contextmanager
def serve(directory):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self,*args): pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(directory)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)


def locator(page, step):
    base = page.locator(step['scope']) if 'scope' in step else page
    if 'selector' in step: return base.locator(step['selector'])
    if 'text' in step: return base.get_by_text(step['text'],exact=step.get('exact',True))
    if 'placeholder' in step: return base.get_by_placeholder(re.compile(step['placeholder'], re.I))
    name = re.compile(step['name'], re.I) if step.get('regex') else step['name']
    roles = step.get('roles', [step.get('role','button')])
    target = base.get_by_role(roles[0],name=name,exact=step.get('exact',True))
    for role in roles[1:]:
        target = target.or_(base.get_by_role(role,name=name,exact=step.get('exact',True)))
    return target



def actions(page, steps):
    results=[]
    for step in steps:
        try:
            target=locator(page,step)
            action=step['action']
            if action=='click': target.click(timeout=5000)
            elif action=='fill': target.fill(step['value'],timeout=5000)
            elif action=='select': target.select_option(step['value'],timeout=5000)
            elif action=='visible':
                target.wait_for(state='visible',timeout=5000)
            elif action=='hidden':
                target.wait_for(state='hidden',timeout=5000)
            elif action=='text':
                if step['value'] not in target.inner_text(timeout=5000): raise AssertionError('expected text absent')
            elif action=='value':
                if target.input_value(timeout=5000)!=step['value']: raise AssertionError('unexpected input value')
            elif action=='count':
                if target.count()!=step['value']: raise AssertionError('unexpected count')
            else: raise ValueError('unknown action')
            page.wait_for_timeout(150)
            results.append(dict(step=step,passed=True))
        except Exception as exc:
            results.append(dict(step=step,passed=False,error=str(exc)))
            break
    return results


def capture(source, out, executable, entry=(), tests=()):
    from playwright.sync_api import sync_playwright
    out=fresh(out);source=Path(source)
    with serve(source.parent) as origin, sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=str(executable),headless=True,
            args=['--disable-background-networking','--disable-component-update','--no-first-run','--disable-quic'])
        try:
            for width,height in [(1280,900),(390,844)]:
                label=f'{width}x{height}';logs=dict(network=[],errors=[],console=[])
                context=browser.new_context(viewport=dict(width=width,height=height),device_scale_factor=1,
                    locale='pt-BR',timezone_id='America/Fortaleza',color_scheme='dark',
                    service_workers='block',reduced_motion='reduce',accept_downloads=False)
                def route(r):
                    url=urlsplit(r.request.url)
                    allowed=url.scheme in {'data','blob'} or (url.scheme=='http' and url.netloc==urlsplit(origin).netloc)
                    logs['network'].append(dict(url=r.request.url,allowed=allowed))
                    r.continue_() if allowed else r.abort('blockedbyclient')
                context.route('**/*',route)
                context.add_init_script("window.open=()=>null; window.WebSocket=class{constructor(){throw Error('offline WebSocket blocked')}}; window.EventSource=class{constructor(){throw Error('offline EventSource blocked')}};")
                if hasattr(context,'route_web_socket'):
                    context.route_web_socket('**/*',lambda ws:ws.close())
                page=context.new_page()
                page.on('pageerror',lambda e:logs['errors'].append(str(e)))
                page.on('console',lambda m:logs['console'].append(dict(type=m.type,text=m.text)))
                page.on('popup',lambda p:p.close())
                page.on('download',lambda d:d.cancel())
                try:
                    page.clock.set_fixed_time(datetime.datetime(2026,10,26,12,tzinfo=datetime.timezone.utc))
                    page.goto(origin+'/'+source.name,wait_until='load',timeout=45000)
                    page.wait_for_timeout(6000)
                    entry_result=actions(page,entry)
                    if any(not r['passed'] for r in entry_result): raise RuntimeError('original route entry failed')
                    page.evaluate('document.fonts.ready')
                    page.screenshot(path=str(out/(label+'.png')),animations='disabled')
                    (out/(label+'.html')).write_text(page.content())
                    write_json(out/(label+'.dom.json'),page.evaluate(DOM))
                    result=actions(page,tests)
                    write_json(out/(label+'.functional.json'),dict(entry=entry_result,steps=result,
                        passed=bool(tests) and len(result)==len(tests) and all(r['passed'] for r in result)))
                    page.screenshot(path=str(out/(label+'.after.png')),animations='disabled')
                except Exception as exc:
                    logs['capture_error']=str(exc)
                    write_json(out/(label+'.functional.json'),dict(passed=False,error=str(exc)))
                finally:
                    write_json(out/(label+'.logs.json'),logs);context.close()
            write_json(out/'browser.json',dict(executable=str(executable),version=browser.version,closed=True))
        finally: browser.close()
