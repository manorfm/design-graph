# Landing implementation verification — t_5c37f74f

Verified locally on 2026-10-26 UTC (2026-10-25 evening, America/Fortaleza), on `pages/landing` from UX base `7ed0ed20a787c8c5395b0af0d9967c3b50fdd96c`. The full design specification, content-source audit, README and pyproject were read. No `.hermes.md` or `AGENTS.md` was found in the worktree or examined ancestors. This records this implementation's execution, independently of inherited Infra evidence.

## Delivered scope

- `site/index.html`, four local assets under `site/assets/` and empty `site/.nojekyll`: seven ordered sections, exact approved English copy, six setup blocks and four fixture-grounded examples. The specimen is labelled illustrative HTML/CSS, with no tool output or simulated execution.
- Default dark forest/cream/lime theme, explicit persisted theme action, guarded storage, progressive enhancement, native FAQ, labelled code scroll areas, clipboard feedback after a resolved write, and manual-copy feedback on failure.
- Standard-library preview/export/static tests under `scripts/pages/`, plus a separately invoked optional browser suite. Reproducible commands are in [local-development.md](local-development.md).
- UX documents, README, pyproject, `src/`, existing runtime tests, MCP/CLI and deployment configuration are unchanged. No publication, production access, secrets, remote push, Kanban operation or `main` modification was performed.

## Commands and results

The available Python initially lacked pytest and Playwright. Created `.venv/` and installed editable development extras and browser tooling:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]' playwright
PLAYWRIGHT_BROWSERS_PATH=.venv/playwright .venv/bin/python -m playwright install chromium
```

Versions: Python 3.14.7; pytest 9.1.1; Playwright 1.64.1; Chromium 156.0.8078.4; Kuzu 0.11.3; MCP 2.3.0. Playwright reported this host unsupported and used its Ubuntu 24.04 browser fallback; it launched successfully without installing system libraries.

| Executed command | Actual result |
|---|---|
| `.venv/bin/python -m pytest -q` | **2642 passed, 7 skipped, 1 warning**, 123.75 seconds. Existing `PytestRemovedIn10Warning` about a class-scoped instance-method fixture in `test_context_benchmark.py`. |
| `python3 scripts/pages/test_static.py` | **5 tests passed**: literal public copy and all six raw code blocks; DOM/hierarchy/assets/fragments/registered URLs/local README anchors; prefix HTTP; isolated export identity and overwrite rejection. |
| `PLAYWRIGHT_BROWSERS_PATH=.venv/playwright .venv/bin/python scripts/pages/test_browser.py` | **21 checks passed**, including the actual clipboard, storage, no-JS, both themes, keyboard and reflow cases below. |
| `python3 scripts/pages/preview.py --port 8000` | Started CLI preview; stdlib `urlopen('http://127.0.0.1:8000/design-graph/')` returned **200**, identical bytes to `site/index.html`; stopped with Ctrl+C. |
| `python3 scripts/pages/export.py .venv/pages-export-final` | Six-file isolated export; SHA-256 manifest matches all six source files exactly, including `.nojekyll`. Earlier export also exercised `.venv/pages-export`. |
| `python3 -m compileall -q scripts/pages` | Passed. |
| `git diff --check` / `git diff --cached --check` | Passed before the local commit. |

The dependency-free HTTP suite fetched `index.html` and every asset under `/design-graph/` with **200** and byte identity. Its intentional requests to `/`, `/README.md` and plain/encoded traversal paths returned **404**. Browser execution recorded **39 HTTP 200**, **4 HTTP 304** cache validations, **zero console messages**, **zero page errors**, and **zero failed requests**. Every browser request remained under the local prefix. External links were compared with the contracted registry and local README heading anchors; remote availability was not probed.

## Browser and visual evidence

All four required viewport sizes were captured in both themes, as viewport and full-page PNGs (16 screenshots). Inspected desktop/tablet/phone captures and full-page compositions locally: desktop contains full proposition, both CTAs and specimen above the fold; small screens retain visible navigation, stacked CTAs, vertical graph labels and wrapping tool notation. Setup rows, task rows, capability index, FAQ and final CTA maintain the specified reading order. Screenshots show the default collapsed pipx alternative; its expanded state was tested separately.

Browser checks covered:

- Dark default despite light OS preference; both theme names and accessible action labels; valid preference surviving reload; theme activation retaining focus/scroll. Invalid stored value and throwing storage methods preserve dark fallback and working toggling.
- All **six** copy buttons, including expanded pipx, wrote exact raw text to the real Chromium clipboard and were read back with `navigator.clipboard.readText()`. Success waits for resolution, announces once through a polite status region, retains focus/width and resets after two seconds. A deliberately pending then rejected write never shows success and displays manual-selection guidance. This injection tests a failure path, not a fake successful clipboard or MCP response.
- No-JS dark content, hidden inert buttons, visible explanatory text, command content, pipx disclosure, native FAQ and setup fragment navigation.
- Skip-link focus/activation; native FAQ via Enter/Space and multiple simultaneous open items; the complete **32-stop** desktop keyboard path with 3px outlines and computed focus contrast ≥3:1.
- No document overflow at 1440×900, 768×1024, 390×844, 320×800, landscape 844×390, or equivalent zoom CSS viewports 640×450 and 320×225, in both themes. At 320px all disclosures were opened together; overflowing code alone remained horizontally scrollable, labelled and keyboard-focusable.
- Reduced-motion disables transitions. All visible action/link/disclosure targets measured at least 44×44px at the required viewports. Settled default text and control/graph boundaries were measured from rendered styles at every required viewport; representative theme-button, primary/secondary action and navigation hover states also passed the contrast checks. Decorative text arrows use muted text color.

| Minimum measured rendered contrast | Dark | Light |
|---|---:|---:|
| Visible text / inherited background | 8.16:1 | 6.02:1 |
| Control or graph boundary / background | 3.31:1 | 3.57:1 |

These minima describe visible default states; individual hover/focus checks assert their relevant thresholds. Text checks apply WCAG AA size/weight thresholds, with opaque computed foreground/background colors. The tests do not constitute full WCAG conformance certification.

Local artifacts, ignored by Git and excluded from export:

- `.venv/pages-evidence/pytest.log`, `static.log`, `browser.log`.
- `.venv/pages-evidence/browser-report.json`: named successful checks, browser version, per-viewport contrast, all HTTP statuses, console/page errors/request failures.
- `.venv/pages-evidence/{dark,light}-{1440x900,768x1024,390x844,320x800}{,-full}.png`.
- `.venv/pages-evidence/export-manifest.json` and `.venv/pages-export-final/`.

## Limits and handoff

This is a Chromium implementation check and local visual review. Firefox, Safari/WebKit, screen readers, native browser zoom controls, forced-colors and mobile hardware were not tested. Reflow was tested using equivalent CSS viewport widths at 200%/400%, not by manipulating browser chrome zoom. No comprehensive automated accessibility auditor was run; computed contrast, DOM semantics and keyboard tests cover the states listed above. Follow-up UX/QA retains the broader accessibility/rendered acceptance review.

The seven project skips remain the existing prototype tests that require private prototype inputs; no private input was supplied. Runtime tests use the installed editable source; no claim of separately tested PyPI-release parity or new MCP execution is made. No external links or final canonical deployment were tested live. All servers started for these checks were stopped. This handoff is a local commit only, with no deploy/Pages setup; the parent agent owns subsequent phase completion.
