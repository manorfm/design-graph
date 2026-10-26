#!/usr/bin/env python3
"""Optional Chromium checks. Run separately; normal pytest never imports Playwright."""
import argparse
import json
from pathlib import Path
import threading

from preview import ROOT, PREFIX, server

# Inspect computed colors, including inherited backgrounds. All landing text
# backgrounds are opaque; this deliberately reports an error for unknown alpha.
CONTRAST = r'''() => {
  function rgb(value) { return value.match(/[\d.]+/g).map(Number); }
  function background(el) {
    if (!el) return [255,255,255];
    const c = rgb(getComputedStyle(el).backgroundColor);
    if (c.length === 4 && c[3] === 0) return background(el.parentElement);
    if (c.length === 4 && c[3] !== 1) throw Error('Unexpected alpha background');
    return c.slice(0,3);
  }
  function luminance(c) {
    return c.map(v => v/255).map(v => v <= .04045 ? v/12.92 : ((v+.055)/1.055)**2.4)
      .reduce((sum,v,i) => sum+v*[.2126,.7152,.0722][i],0);
  }
  function ratio(a,b) { const x=luminance(a), y=luminance(b); return (Math.max(x,y)+.05)/(Math.min(x,y)+.05); }
  const failures=[]; let minimum=100; let textNodes=0;
  const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  for(let n; n=walker.nextNode();) {
    const el=n.parentElement;
    if(!n.textContent.trim() || ['SCRIPT','STYLE','NOSCRIPT'].includes(el.tagName)) continue;
    const range=document.createRange(); range.selectNode(n);
    if(!range.getBoundingClientRect().width || !el.checkVisibility()) continue;
    if(el.closest('#copy-status')) continue;
    const style=getComputedStyle(el), size=parseFloat(style.fontSize);
    const large=size>=24 || (size>=18.66 && Number(style.fontWeight)>=700);
    const contrast=ratio(rgb(style.color).slice(0,3),background(el));
    minimum=Math.min(minimum,contrast); textNodes++;
    if(contrast < (large ? 3 : 4.5)) failures.push({text:n.textContent,contrast});
  }
  const boundaries=[];
  for(const el of document.querySelectorAll('button,.button,.node')) {
    if(!el.checkVisibility()) continue;
    const style=getComputedStyle(el);
    // Filled primary buttons have a boundary defined by their background.
    const color=el.classList.contains('primary') ? background(el) : rgb(style.borderTopColor).slice(0,3);
    const contrast=ratio(color,background(el.parentElement)); boundaries.push(contrast);
    if(contrast<3) failures.push({boundary:el.textContent,contrast});
  }
  const focused=document.querySelector(':focus-visible');
  const focusContrast=focused && getComputedStyle(focused).outlineStyle === 'solid' ? ratio(rgb(getComputedStyle(focused).outlineColor).slice(0,3),background(focused.parentElement)) : null;
  return {focusContrast,minimumText:minimum,minimumBoundary:Math.min(...boundaries),textNodes,failures};
}'''


def settle_visual_state(page, *, neutral=False, timeout=5000):
    """Wait for rendered styles/layout, without changing focus or CSS motion.

    Neutral measurements park the pointer outside the viewport, including after
    resize/scroll. Intentional hover and keyboard callers retain their state.
    A deadline rejects perpetual animation; contrast errors are never retried.
    """
    if neutral:
        page.mouse.move(-1, -1)
    return page.evaluate(r'''timeout => new Promise((resolve, reject) => {
      let previous, unchanged = 0, frame;
      const start = performance.now();
      const timer = setTimeout(() => {
        cancelAnimationFrame(frame);
        reject(new Error(`Visual state did not stabilize within ${timeout}ms`));
      }, timeout);
      function sample() {
        // Reading computed styles flushes pending hover/media-query changes
        // before querying animations (including CSS transitions).
        const signature = JSON.stringify(Array.from(document.querySelectorAll('*'), el => {
          const s = getComputedStyle(el), r = el.getBoundingClientRect();
          return [s.display, s.visibility, s.opacity, s.color, s.backgroundColor,
            s.borderTopColor, s.outlineColor, s.outlineStyle, s.outlineWidth,
            s.outlineOffset, s.fontSize, s.fontWeight, r.x, r.y, r.width, r.height];
        }));
        const active = document.getAnimations().some(a => a.pending || a.playState === 'running');
        unchanged = !active && signature === previous ? unchanged + 1 : 0;
        previous = signature;
        if (unchanged >= 2) {
          clearTimeout(timer);
          resolve({elapsedMs: performance.now() - start});
        } else {
          frame = requestAnimationFrame(sample);
        }
      }
      frame = requestAnimationFrame(sample);
    })''', timeout)


def measure_contrast(page, *, neutral=True, timeout=5000):
    settle_visual_state(page, neutral=neutral, timeout=timeout)
    return page.evaluate(CONTRAST)


def run(output):
    from playwright.sync_api import sync_playwright, expect

    output.mkdir(parents=True, exist_ok=True)
    report = {'checks': [], 'console': [], 'pageerror': [], 'http': [], 'failedRequests': [], 'contrast': []}

    def passed(name):
        report['checks'].append(name)
        print('PASS', name, flush=True)

    with server(0) as httpd:
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{httpd.server_port}'
        url = base + PREFIX
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                report['browser'] = browser.version

                def context(**kwargs):
                    ctx = browser.new_context(**kwargs)
                    ctx.on('page', observe)
                    return ctx

                def observe(page):
                    page.on('console', lambda m: report['console'].append({'type': m.type, 'text': m.text}))
                    page.on('pageerror', lambda e: report['pageerror'].append(str(e)))
                    page.on('response', lambda r: report['http'].append({'url': r.url, 'status': r.status}))
                    page.on('requestfailed', lambda r: report['failedRequests'].append({'url': r.url, 'failure': r.failure}))

                ctx = context(permissions=['clipboard-read', 'clipboard-write'])
                page = ctx.new_page()
                page.goto(url)
                expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
                page.emulate_media(color_scheme='light')
                page.reload()
                expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
                passed('dark default regardless of OS')

                for theme in ('dark', 'light'):
                    if theme == 'light':
                        page.get_by_role('button', name='Switch to light theme').click()
                    for width, height in ((1440,900),(1280,900),(768,1024),(390,844),(320,800)):
                        page.set_viewport_size({'width': width, 'height': height})
                        page.evaluate('window.scrollTo(0,0)')
                        expect(page.locator('html')).to_have_attribute('data-theme', theme)
                        assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')
                        targets = page.locator('a:visible,button:visible,summary:visible').evaluate_all(
                            'items => items.filter(e => { const r=e.getBoundingClientRect(); return r.width < 44 || r.height < 44; }).map(e => e.outerHTML)')
                        assert not targets, targets
                        contrast = measure_contrast(page)
                        assert not contrast['failures'], contrast
                        report['contrast'].append({'theme':theme,'width':width,**contrast})
                        name = f'{theme}-{width}x{height}'
                        page.screenshot(path=str(output / f'{name}.png'))
                        page.screenshot(path=str(output / f'{name}-full.png'), full_page=True)
                        passed(f'{name}: overflow, rendered contrast, screenshots')
                    # Hover states, keyboard outlines, native FAQ in both themes.
                    page.set_viewport_size({'width':1440,'height':900})
                    for selector in ('button#theme','.button.primary','.button:not(.primary)','nav a'):
                        page.locator(selector).first.hover()
                        assert not measure_contrast(page, neutral=False)['failures']
                    page.goto(url)
                    page.keyboard.press('Tab')
                    expect(page.locator('.skip')).to_be_focused()
                    assert page.locator('.skip').evaluate('el => el.getBoundingClientRect().top >= 0')
                    page.keyboard.press('Enter')
                    expect(page.locator('#main')).to_be_focused()
                    summaries = page.locator('#faq summary')
                    summaries.nth(1).focus()
                    page.keyboard.press('Enter')
                    assert page.locator('#faq details').nth(1).get_attribute('open') is not None
                    assert page.locator('#faq details').first.get_attribute('open') is not None
                    page.keyboard.press('Space')
                    assert page.locator('#faq details').nth(1).get_attribute('open') is None
                    passed(f'{theme}: hover contrast, skip link, keyboard FAQ, multiple open')

                # All six blocks, including pipx, use the actual browser clipboard.
                page.set_viewport_size({'width':1440,'height':900})
                page.locator('.pipx summary').click()
                for i in range(6):
                    button = page.locator(f'[data-copy="code-{i}"]')
                    width = button.bounding_box()['width']
                    button.click()
                    expect(button).to_have_text('Copied')
                    expect(button).to_be_focused()
                    assert abs(button.bounding_box()['width'] - width) < 1
                    assert page.evaluate('navigator.clipboard.readText()') == page.locator(f'#code-{i}').text_content()
                    expect(page.locator('#copy-status')).to_have_text('Copied to clipboard.')
                expect(page.locator('[data-copy="code-5"]')).to_have_text('Copy command', timeout=3000)
                passed('six real clipboard writes, exact bytes, stable widths/focus, feedback/reset')

                # A pending write must never announce success; reject it explicitly.
                page.evaluate('''() => { navigator.clipboard.writeText = () => new Promise((resolve,reject) => { window.rejectCopy=reject; }); }''')
                button = page.locator('[data-copy="code-0"]')
                button.click()
                expect(button).to_have_text('Copy command')
                page.evaluate("window.rejectCopy(new Error('Permission denied'))")
                expect(page.locator('#copy-status')).to_have_text('Copy unavailable. Select and copy the code manually.')
                expect(page.locator('.copy-feedback')).to_be_visible()
                expect(button).to_be_focused()
                passed('pending/rejected clipboard is honest, visible manual-copy guidance')

                # Toggle retains scroll/focus and persists a valid preference.
                page.evaluate('window.scrollTo(0,0)')
                button = page.locator('#theme')
                button.focus()
                before = page.evaluate('scrollY')
                page.keyboard.press('Enter')
                expect(button).to_be_focused()
                assert page.evaluate('scrollY') == before
                saved = page.evaluate("localStorage.getItem('design-graph-theme')")
                page.reload()
                expect(page.locator('html')).to_have_attribute('data-theme', saved)
                passed('theme persistence, keyboard activation, stable focus/scroll')

                for storage_mode in ('invalid','blocked'):
                    fresh = context()
                    if storage_mode == 'invalid':
                        fresh.add_init_script("if (location.protocol === 'http:') localStorage.setItem('design-graph-theme', 'unexpected')")
                    else:
                        fresh.add_init_script("Storage.prototype.getItem = Storage.prototype.setItem = () => { throw new Error('Storage blocked'); }")
                    p = fresh.new_page()
                    p.goto(url)
                    expect(p.locator('html')).to_have_attribute('data-theme','dark')
                    p.locator('#theme').click()
                    expect(p.locator('html')).to_have_attribute('data-theme','light')
                    fresh.close()
                    passed(f'{storage_mode} storage: dark fallback and working toggle')

                nojs = context(java_script_enabled=False, viewport={'width':320,'height':800})
                p = nojs.new_page()
                p.goto(url)
                expect(p.locator('html')).to_have_attribute('data-theme','dark')
                expect(p.locator('#theme')).to_be_hidden()
                assert p.locator('[data-copy]:visible').count() == 0
                expect(p.locator('.no-js')).to_be_visible()
                expect(p.locator('.no-js')).to_contain_text('Commands can still be selected manually.')
                p.locator('.pipx summary').click()
                expect(p.locator('#code-1')).to_be_visible()
                selected = p.locator('#code-1').evaluate('''el => {
                    const range=document.createRange(); range.selectNodeContents(el);
                    const selection=getSelection(); selection.removeAllRanges(); selection.addRange(range);
                    return selection.toString();
                }''')
                assert selected == 'pipx install design-graph'
                assert p.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')
                p.locator('#faq summary').nth(1).click()
                expect(p.locator('#faq details').nth(1)).to_have_attribute('open','')
                p.get_by_role('link',name='Setup',exact=True).click()
                expect(p.locator('#setup h2')).to_be_in_viewport()
                nojs.close()
                passed('no-JS: hidden inert buttons, copy selection content, native FAQ, fragments')

                # Traverse the complete keyboard path; verify every focused control
                # has a rendered 3px ring with >=3:1 contrast using palette checks.
                page.goto(url)
                page.locator('.pipx').evaluate('el => el.open = true')
                settle_visual_state(page, neutral=True)
                page.evaluate('document.activeElement.blur()')
                page.locator('.skip').focus()
                expected_stops = set(page.evaluate('''() => Array.from(document.querySelectorAll('a,button,summary,pre'))
                    .map((e,i) => e.tabIndex >= 0 && e.checkVisibility() ? i : null).filter(i => i !== null)'''))
                seen = {0}
                for _ in range(100):
                    page.keyboard.press('Tab')
                    settle_visual_state(page)
                    focus = page.evaluate('''() => {
                      const e=document.activeElement,s=getComputedStyle(e);
                      return {tag:e.tagName,key:Array.from(document.querySelectorAll('a,button,summary,pre')).indexOf(e),outline:s.outlineStyle,width:s.outlineWidth,offset:s.outlineOffset};
                    }''')
                    if focus['tag'] == 'BODY':
                        break
                    assert focus['outline'] == 'solid' and focus['width'] == '3px' and focus['offset'] == '3px', focus
                    assert measure_contrast(page, neutral=False)['focusContrast'] >= 3
                    seen.add(focus['key'])
                assert seen == expected_stops, {'seen': sorted(seen), 'expected': sorted(expected_stops)}
                passed(f'full keyboard path: {len(seen)} distinct controls/code stops with visible ring')

                page.emulate_media(reduced_motion='reduce')
                assert page.locator('#theme').evaluate("el => getComputedStyle(el).transitionDuration") == '0s'
                for theme in ('dark','light'):
                    page.evaluate('(theme) => document.documentElement.dataset.theme=theme',theme)
                    for width,height in ((844,390),(640,450),(320,225)):
                        page.set_viewport_size({'width':width,'height':height})
                        assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')
                        assert not measure_contrast(page)['failures']
                passed('reduced motion, phone landscape, 200%/400% equivalent CSS viewport reflow')
                page.set_viewport_size({'width':320,'height':800})
                page.locator('details').evaluate_all('items => items.forEach(el => el.open = true)')
                page.wait_for_timeout(100)
                assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')
                for pre in page.locator('pre').all():
                    if pre.evaluate('el => el.scrollWidth > el.clientWidth'):
                        assert pre.get_attribute('tabindex') == '0'
                        assert pre.get_attribute('aria-label')
                        pre.focus()
                        page.keyboard.press('End')
                passed('320px: all disclosures open, labelled overflowing code keyboard-focusable')
                assert not report['pageerror'], report['pageerror']
                assert not report['console'], report['console']
                assert not report['failedRequests'], report['failedRequests']
                assert all(r['status'] in (200, 304) and r['url'].startswith(url) for r in report['http'])
                passed('zero console/pageerror/request failures; all HTTP 200/304 and prefix-local')
                browser.close()
        finally:
            httpd.shutdown()
            thread.join()
            (output / 'browser-report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f'Evidence: {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.venv/pages-evidence')
    args = parser.parse_args()
    destination = args.output.resolve()
    if not destination.is_relative_to(ROOT) or destination.is_relative_to(ROOT / 'site'):
        parser.error('Keep evidence inside this worktree and outside site/.')
    run(destination)
