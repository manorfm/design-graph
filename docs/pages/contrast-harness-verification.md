# Contrast harness verification — t_af2681c3

Executed locally on 2026-10-26 UTC in `fix/contrast-harness-t_af2681c3`, from exact base `8d712f400b90cfe6f71d0e5a455423547a67b381`. Only the browser harness, its separate regression script and this document changed. `site/` is unchanged. Changes are committed locally for TL review; no push, merge or publication was made.

## Mechanism

`settle_visual_state()` parks the pointer at (-1, -1) for neutral measurements, flushes computed styles/layout on animation frames, and requires three matching consecutive samples with no running or pending document animations. Samples include rendered colors, typography, outlines, visibility, opacity and element rectangles. The default deadline is 5000 ms; an unfinished animation fails explicitly. This replaces fixed 180 ms contrast sleeps without changing CSS or disabling motion.

`measure_contrast()` synchronizes before evaluating the original `CONTRAST` exactly once. Every original contrast call uses it: both themes at four screenshot sizes, intentional hovers, the complete keyboard path, and landscape/equivalent zoom reflow. Hover calls retain the pointer with `neutral=False`; keyboard synchronization never blurs or clicks. A regression also checks that pointer neutralization retains keyboard `:focus-visible`.

`CONTRAST` is byte-for-byte identical to the base, and all 27 original Python assertions remain. Text thresholds remain 4.5:1 (normal) / 3:1 (large), boundaries and focus remain 3:1, and unknown background alpha remains an error. There is no contrast-error retry or suppression in the harness.

## Deterministic regression

`scripts/pages/test_browser_stability.py` uses the actual local landing and its unmodified 140 ms CSS transition. In each theme it hovers the theme button at 1440 px, then resizes to 768 px while retaining the pointer coordinate. A `transitionrun` listener pauses the real outgoing background transition at 70 ms, so the intermediate observation does not depend on Python/IPC speed. This instrumentation exists only in the separate regression. The transition resumes before the corrected harness runs.

- **RED:** raw `page.evaluate(CONTRAST)` raises `Unexpected alpha background` in both themes. Recorded backgrounds: dark `rgba(24, 35, 30, 0.314)`; light `rgba(255, 255, 255, 0.314)`.
- **GREEN:** the corrected harness waits for the final transparent background and passes unchanged contrast checks in both themes. Separate controls verify retained intentional hover and removed neutral hover.
- Persistent alpha still raises after settling. Invalid final text and boundary colors still return failures. An in-memory fixture checks colors immediately below and above 4.5:1 / 3:1.
- Infinite animation fails at the requested 250 ms deadline (266.64 ms observed including Playwright overhead), rather than waiting indefinitely.

The final regression completed **13 controls**. Expected exceptions are asserted and recorded only by its negative controls. This demonstrates a deterministic hover/resize transition mechanism; it does **not** establish reproduction of the historical TL failure.

## Executed commands and evidence

Tooling: Python **3.14.8**, Playwright **1.64.1**, Chromium **156.0.8078.4**. Created a local `.venv` with `uv` and installed only Playwright and its dependencies; project/MCP extras and the optional historical Python suite were unnecessary for these checks. The existing compatible browser cache was used read-only; no browser download or system-package installation was needed.

Setup used (from the worktree root):

```bash
mkdir -p .venv/contrast-evidence .venv/uv-cache .venv/tmp
UV_CACHE_DIR="$PWD/.venv/uv-cache" TMPDIR="$PWD/.venv/tmp" uv venv --python python3 .venv --allow-existing
UV_CACHE_DIR="$PWD/.venv/uv-cache" TMPDIR="$PWD/.venv/tmp" uv pip install --python .venv/bin/python playwright
export TMPDIR="$PWD/.venv/tmp"
export XDG_CACHE_HOME="$PWD/.venv/cache"
export PLAYWRIGHT_BROWSERS_PATH=/home/manoelmedeiros/.cache/ms-playwright
```

Executed the regression with separate final evidence:

```bash
.venv/bin/python scripts/pages/test_browser_stability.py --output .venv/contrast-evidence/stability-final > .venv/contrast-evidence/stability-final.log 2>&1
```

Executed the complete original suite five times, each with its own output directory and log. Equivalent repeat command (the recorded runs 2–5 used a sequential Python subprocess loop that also recorded elapsed time and exit codes):

```bash
for n in 1 2 3 4 5; do
  .venv/bin/python scripts/pages/test_browser.py --output ".venv/contrast-evidence/run-$n" > ".venv/contrast-evidence/run-$n.log" 2>&1 || break
done
.venv/bin/python scripts/pages/test_static.py > .venv/contrast-evidence/static.log 2>&1
git diff --check > .venv/contrast-evidence/diff-check.log 2>&1
```

| Actual execution | Result | JSON and screenshots under `.venv/contrast-evidence/` |
|---|---|---|
| Browser run 1 | 21 PASS, exit 0 | `run-1/browser-report.json`, 16 PNGs |
| Browser run 2 | 21 PASS, exit 0 | `run-2/browser-report.json`, 16 PNGs |
| Browser run 3 | 21 PASS, exit 0 | `run-3/browser-report.json`, 16 PNGs |
| Browser run 4 | 21 PASS, exit 0 | `run-4/browser-report.json`, 16 PNGs |
| Browser run 5 | 21 PASS, exit 0 | `run-5/browser-report.json`, 16 PNGs |
| Final stability regression | 13 PASS, exit 0 | `stability-final/stability-report.json`, 4 PNGs |
| Static suite | 5 passed, exit 0 | `static.log` |
| Diff whitespace check | Passed, exit 0 | `diff-check.log` |

All five browser reports have zero console messages, page errors and failed requests, and the same 21 named checks, including 32 keyboard stops. Each contains eight per-viewport contrast records; minimum neutral text contrast is 6.015:1 and boundary contrast 3.310:1 across both themes. Logs are `run-1.log` through `run-5.log`; `repeat-executions.json` records runs 2–5. `verification-summary.json` validates report/log counts and records source hashes. The earlier 11-control development regression and its screenshots remain in `stability/` and `stability.log`; the final 13-control regression is authoritative.

Independent parent verification reran the final regression (13 PASS), the complete browser suite (21 PASS) and the static suite (5 passed), all exit 0. Evidence is in `parent-stability/`, `parent-browser/` and the corresponding `parent-*.log` files. This is an additional sixth complete browser run, not one of the five rows above.

## Limits

Evidence is local Chromium only, with the accessibility limits already described in [implementation-verification.md](implementation-verification.md). Three stable frames and completed current animations do not predict arbitrary future asynchronous changes. A perpetual document animation deliberately fails the bounded wait. The regression pauses a real transition for deterministic observation; normal suite runs use natural transitions. No Firefox/WebKit, screen reader, production deployment or historical Python suite was tested. All owned preview servers and browsers terminated; evidence remains ignored under `.venv/`.
