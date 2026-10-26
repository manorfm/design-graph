"""Preparador privado: original file://, sem servidor e sem reconstrução."""
from pathlib import Path
import datetime
import time

from .common import fresh, write_json, digest

DOM = """() => ({text: document.body.innerText, controls:
 [...document.querySelectorAll('button,input,select,textarea,a')].map(e => ({
 tag:e.tagName,text:e.innerText,placeholder:e.getAttribute('placeholder'),
 type:e.getAttribute('type'),value:e.value,disabled:e.disabled,
 visible:!!(e.getClientRects().length && getComputedStyle(e).visibility!=='hidden')}))})"""


def target(page, step):
    if step.get('scope_role'):
        page = page.get_by_role(step['scope_role'])
    if 'placeholder' in step:
        return page.get_by_placeholder(step['placeholder'], exact=True)
    if 'text' in step:
        return page.get_by_text(step['text'], exact=True)
    return page.get_by_role(step.get('role', 'button'), name=step['name'], exact=True)


def action(page, step):
    loc = target(page, step)
    if 'nth' in step:
        loc = loc.nth(step['nth'])
    op = step.get('action', 'click')
    if op == 'click': loc.click()
    elif op == 'fill': loc.fill(step['value'])
    elif op == 'select': loc.select_option(step['value'])
    elif op == 'visible': loc.wait_for(state='visible')
    elif op == 'hidden': loc.wait_for(state='hidden')
    elif op == 'disabled':
        if not loc.is_disabled(): raise ValueError('control is not disabled')
    elif op == 'inert':
        before = page.evaluate(DOM)
        loc.click(); page.wait_for_timeout(300)
        if page.evaluate(DOM) != before: raise ValueError('observable state changed')
    else: raise ValueError('unsupported oracle action')
    page.wait_for_timeout(250)


def capture(source, out, plans):
    """Plans contain preparer-only navigation and assertions; never agent input."""
    from playwright.sync_api import sync_playwright
    started = time.monotonic(); out = fresh(out)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width, height in [(1280, 900), (390, 844)]:
                for key, plan in plans.items():
                    folder = fresh(out/f'{key}-{width}x{height}')
                    logs = {'network': [], 'errors': [], 'downloads': [], 'steps': []}
                    context = browser.new_context(viewport={'width':width,'height':height},
                        locale='pt-BR',timezone_id='America/Fortaleza',service_workers='block',
                        reduced_motion='reduce',accept_downloads=False)
                    def route(r):
                        allowed = r.request.url.startswith(('file:', 'data:', 'blob:'))
                        logs['network'].append({'url':r.request.url,'allowed':allowed})
                        r.continue_() if allowed else r.abort()
                    context.route('**/*', route)
                    context.add_init_script("window.WebSocket=class{constructor(){throw Error('offline')}};window.EventSource=window.WebSocket;window.open=()=>null")
                    if hasattr(context,'route_web_socket'):
                        context.route_web_socket('**/*',lambda ws:ws.close())
                    page = context.new_page()
                    page.on('pageerror',lambda e:logs['errors'].append(str(e)))
                    page.on('download',lambda d:(logs['downloads'].append(d.suggested_filename),d.cancel()))
                    page.on('popup',lambda p:p.close())
                    try:
                        page.clock.set_fixed_time(datetime.datetime(2026,10,26,12,tzinfo=datetime.timezone.utc))
                        page.goto(Path(source).resolve().as_uri(),wait_until='load')
                        page.wait_for_timeout(2500)
                        for step in plan['entry']: action(page, step)
                        for i, step in enumerate([None, *plan['steps']]):
                            if step: action(page, step)
                            page.screenshot(path=str(folder/f'{i:02}.png'),animations='disabled')
                            write_json(folder/f'{i:02}.json',page.evaluate(DOM))
                            logs['steps'].append({'step':step,'passed':True})
                        if logs['errors']: raise ValueError('original browser errors')
                    except Exception as exc:
                        logs['failure'] = str(exc)
                        raise
                    finally:
                        write_json(folder/'observations.json',logs)
                        context.close()
            write_json(out/'receipt.json',{'source_sha256':digest(source),'browser':browser.version,
                'seconds':time.monotonic()-started,'transport':'file://','listener':False,
                'passed':True,'plans':plans})
        finally: browser.close()
    return out
