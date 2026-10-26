#!/usr/bin/env python3
"""Deterministic local Chromium contrast controls, separate from the 21 checks."""
import argparse
import json
import threading
import time
from pathlib import Path

from playwright.sync_api import Error, sync_playwright

from preview import PREFIX, ROOT, server
from test_browser import CONTRAST, measure_contrast, settle_visual_state


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    report = {'checks': [], 'controls': []}

    def passed(name, **details):
        report['checks'].append(name)
        report['controls'].append({'name': name, **details})
        print('PASS', name, flush=True)

    def rejected(action, message):
        # Only negative controls expect errors. Production measurement never
        # catches/retries a CONTRAST failure.
        try:
            action()
        except Error as error:
            assert message in str(error), str(error)
            return str(error)
        raise AssertionError(f'Expected rejection: {message}')

    with server(0) as httpd:
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    report['browser'] = browser.version
                    page = browser.new_page(viewport={'width': 1440, 'height': 900})
                    page.goto(f'http://127.0.0.1:{httpd.server_port}{PREFIX}')
                    for theme in ('dark', 'light'):
                        page.set_viewport_size({'width': 1440, 'height': 900})
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        assert not measure_contrast(page)['failures']
                        page.locator('#theme').hover()
                        assert not measure_contrast(page, neutral=False)['failures']
                        assert page.locator('#theme').evaluate("el => el.matches(':hover')")
                        # Keep the desktop pointer coordinate through resize.
                        # The real 140ms outgoing background transition is held
                        # at its midpoint using the Web Animations API, avoiding
                        # dependence on Python/IPC speed for the RED observation.
                        page.locator('#theme').evaluate('''el => {
                          window.heldContrastTransition = null;
                          const hold = event => {
                            if (event.propertyName !== 'background-color') return;
                            const a = el.getAnimations().find(a => a.transitionProperty === 'background-color');
                            a.pause(); a.currentTime = a.effect.getTiming().duration / 2;
                            window.heldContrastTransition = a;
                            el.removeEventListener('transitionrun', hold);
                          };
                          el.addEventListener('transitionrun', hold);
                        }''')
                        page.set_viewport_size({'width': 768, 'height': 1024})
                        page.wait_for_function('() => window.heldContrastTransition !== null')
                        transient = page.locator('#theme').evaluate('''el => ({
                          background: getComputedStyle(el).backgroundColor,
                          hovered: el.matches(':hover'),
                          duration: window.heldContrastTransition.effect.getTiming().duration,
                          currentTime: window.heldContrastTransition.currentTime
                        })''')
                        assert transient['duration'] == 140, transient
                        assert not transient['hovered'], transient
                        error = rejected(lambda: page.evaluate(CONTRAST), 'Unexpected alpha background')
                        passed(f'{theme}: RED raw CONTRAST rejects transient hover/resize alpha',
                               transient=transient, expectedError=error)
                        page.screenshot(path=str(output / f'{theme}-transient.png'), animations='allow')
                        page.evaluate('window.heldContrastTransition.play()')
                        result = measure_contrast(page)
                        assert not result['failures'], result
                        assert page.locator('#theme').evaluate(
                            "el => !el.matches(':hover') && getComputedStyle(el).backgroundColor === 'rgba(0, 0, 0, 0)'")
                        passed(f'{theme}: GREEN neutral harness waits for final state', contrast=result)
                        page.screenshot(path=str(output / f'{theme}-settled.png'))

                        # Neutralization must also remove an already settled
                        # hover; intentional hover must remain available.
                        page.locator('#theme').hover()
                        result = measure_contrast(page, neutral=False)
                        assert not result['failures'], result
                        assert page.locator('#theme').evaluate("el => el.matches(':hover')")
                        measure_contrast(page)
                        assert not page.locator('#theme').evaluate("el => el.matches(':hover')")
                        passed(f'{theme}: intentional hover retained, neutral hover removed')

                    page.reload()
                    settle_visual_state(page, neutral=True)
                    page.keyboard.press('Tab')
                    assert page.locator('.skip').evaluate("el => el.matches(':focus-visible')")
                    result = measure_contrast(page)
                    assert result['focusContrast'] >= 3, result
                    assert page.locator('.skip').evaluate("el => el === document.activeElement && el.matches(':focus-visible')")
                    passed('neutral measurement preserves keyboard focus-visible', contrast=result)

                    page.locator('#theme').evaluate("el => el.style.backgroundColor = 'rgba(255, 255, 255, .5)'")
                    error = rejected(lambda: measure_contrast(page), 'Unexpected alpha background')
                    passed('persistent alpha still rejected after settling', expectedError=error)
                    page.reload()
                    page.locator('body').evaluate("el => el.style.color = getComputedStyle(el).backgroundColor")
                    result = measure_contrast(page)
                    assert result['failures'] and result['minimumText'] == 1, result
                    passed('invalid final text contrast still fails AA', contrast=result)
                    page.reload()
                    page.locator('#theme').evaluate("el => el.style.borderColor = getComputedStyle(document.body).backgroundColor")
                    result = measure_contrast(page)
                    assert any('boundary' in failure and failure['contrast'] < 3 for failure in result['failures']), result
                    passed('invalid final boundary contrast still fails 3:1', contrast=result)

                    # Values immediately below/above the unchanged AA cutoffs.
                    # This isolated in-memory fixture never modifies site/.
                    page.set_content('''<body style="background: white; color: black">
                      <p style="font-size: 17px; color: #777">Normal text</p>
                      <p style="font-size: 24px; color: #959595">Large text</p>
                      <button style="color: black; background: white; border: 1px solid #959595">Boundary</button>
                    </body>''')
                    result = measure_contrast(page)
                    assert len(result['failures']) == 3, result
                    normal, large, boundary = result['failures']
                    assert 4.4 < normal['contrast'] < 4.5, normal
                    assert 2.9 < large['contrast'] < 3, large
                    assert 2.9 < boundary['contrast'] < 3, boundary
                    passed('AA cutoffs reject near-threshold text and boundaries', contrast=result)
                    page.locator('p').nth(0).evaluate("el => el.style.color = '#767676'")
                    page.locator('p').nth(1).evaluate("el => el.style.color = '#949494'")
                    page.locator('button').evaluate("el => el.style.borderColor = '#949494'")
                    result = measure_contrast(page)
                    assert not result['failures'], result
                    passed('AA cutoffs accept just-valid final colors', contrast=result)

                    page.goto(f'http://127.0.0.1:{httpd.server_port}{PREFIX}')
                    page.locator('#theme').evaluate("el => el.animate([{opacity: 1}, {opacity: .5}], {duration: 140, iterations: Infinity})")
                    start = time.monotonic()
                    error = rejected(lambda: measure_contrast(page, timeout=250), 'Visual state did not stabilize within 250ms')
                    elapsed = (time.monotonic() - start) * 1000
                    assert elapsed < 2000, elapsed
                    passed('perpetual animation fails with bounded timeout', expectedError=error, elapsedMs=elapsed)
                finally:
                    browser.close()
        finally:
            httpd.shutdown()
            thread.join()
            (output / 'stability-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'Evidence: {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.venv/contrast-evidence/stability')
    args = parser.parse_args()
    destination = args.output.resolve()
    if not destination.is_relative_to(ROOT) or destination.is_relative_to(ROOT / 'site'):
        parser.error('Keep evidence inside this worktree and outside site/.')
    run(destination)
