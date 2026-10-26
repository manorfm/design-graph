# Landing: local development

The landing is the complete contents of `site/`. Open `site/index.html` directly for a basic no-build preview, or use the prefix-aware HTTP preview below. CSS, JavaScript and SVG are local; there are no web runtime dependencies, backend, fonts, analytics or network asset requests. The package's CLI/MCP is independent of the landing.

Run commands from the repository root. Python 3.10+ is sufficient for preview, export and static checks.

## Preview at the Pages prefix

```bash
python3 scripts/pages/preview.py --port 8000
```

Visit <http://127.0.0.1:8000/design-graph/>. Stop with **Ctrl+C**. The server binds only to loopback, serves only `site/`, redirects `/design-graph` to the trailing slash, and rejects paths outside `/design-graph/`. It does not expose repository files or directory listings. A busy port fails explicitly; choose another with `--port`.

Fragment navigation and all content work without JavaScript. Theme/copy controls appear only when enhanced. Clipboard access requires a secure browser context (localhost or HTTPS); an unavailable or denied clipboard shows manual-copy guidance. Theme storage is optional and guarded.

## Export without publishing

Choose a destination that does not yet exist, inside this worktree and outside `site/`:

```bash
python3 scripts/pages/export.py .venv/pages-export
```

This copies only the six files in `site/`, including the empty `.nojekyll`, with identical bytes. It rejects symlinks and existing destinations. It does not create a branch, configure Pages, publish or contact a remote. Export root is the page root: do not nest an extra `site/` directory when handing the contents to a later publishing phase. Relative assets allow the export to be hosted at `/design-graph/`.

## Tests

Dependency-free contract checks (DOM structure, all approved public literals, six setup blocks including pipx, four examples, assets, links/fragments, README anchors, prefix HTTP and export):

```bash
python3 scripts/pages/test_static.py
```

The export test creates and removes a temporary directory under `.venv/`; it needs no installed packages. HTTP tests start an ephemeral loopback server and stop it automatically. The export destination is compared byte-for-byte against `site/`.

For project regression tests, install the development extras into a local virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

Browser tests are a separate, optional command. They are outside pytest's configured `testpaths`, and normal pytest does not import Playwright. Install Chromium in this worktree:

```bash
.venv/bin/python -m pip install playwright
PLAYWRIGHT_BROWSERS_PATH=.venv/playwright .venv/bin/python -m playwright install chromium
PLAYWRIGHT_BROWSERS_PATH=.venv/playwright .venv/bin/python scripts/pages/test_browser.py
```

A supported Chromium host with its system libraries is needed. The current host ran Playwright's Ubuntu 24.04 fallback successfully; no system-package installation was needed. Installation downloads are test tooling only, never landing dependencies. A missing browser/tool is an explicit error for this optional command.

The browser suite starts and stops its own ephemeral preview. It exercises the actual browser clipboard for all six blocks, a pending/rejected clipboard, storage, no-JS, keyboard/FAQ/focus, both themes, computed contrast and overflow. It captures console, page errors, request failures and HTTP statuses into `.venv/pages-evidence/browser-report.json`. Viewport and full-page screenshots use `dark|light-WIDTHxHEIGHT[-full].png` at 1440×900, 768×1024, 390×844 and 320×800. Evidence stays in ignored `.venv/`, outside `site/` and outside commits. An optional `--output` must remain inside the worktree and outside `site/`.

The suite also checks landscape 844×390 and 640×450 / 320×225 CSS viewport reflow, equivalent to a 1280×900 viewport at 200% / 400%. This is not a native browser zoom-control test. See [implementation-verification.md](implementation-verification.md) for executed results and accessibility limits.
