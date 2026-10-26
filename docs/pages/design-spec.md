# Design Graph — landing direction

Status: implementable UX contract for t_5c37f74f. Public copy is English; implementation notes are English for one consistent handoff. Sources and limitations: [content-sources.md](content-sources.md). Source baseline: `ebdbeb24323d7143e0186622a7389b963e5ed350`.

## 1. Scope and editorial decision

Build a static, readable product introduction for frontend developers and designers handing HTML prototypes to coding agents. The conversion is **start local setup**, not subscribe, authenticate or connect to a hosted service. Explain the path HTML → graph → scoped context before asking readers to configure MCP.

Deliver `site/index.html`, `site/assets/` for local CSS/JS/SVG, and empty `site/.nojekyll`. No mandatory build/backend, package-runtime edits, analytics, remote fonts, CDNs, cookies or simulated tool execution. Final base path is `/design-graph/`; use relative asset paths and fragment navigation. Publishing is TL-only on `gh-pages`, not this phase or the dev phase. No `main` edits/pushes. No pre-existing DESIGN.md or project instruction files were found in this baseline; this document sets the landing's direction only.

Reference: Taplio's MCP page was read as extracted text, not visually audited. Borrow the cadence explain → setup → tasks → deeper capabilities → FAQ → repeated CTA. Do not borrow its brand, visual identity, copy, integrations, hosted transport, account model, numerical claims or client badges. Our own identity: **a technical field guide, with a graph specimen as the central illustration**.

## 2. Visual direction: Graph field guide

A quiet forest-black canvas, warm near-white type, sharp lime actions, thin connective rules, compact monospace annotations and a large editorial headline. No gradients, purple glow, stock photos, decorative dashboard chrome, floating chat bubbles, blinking status dots or logo strips. No generic equal-card grid for the entire page. Mix a split hero, broad explanatory strip, numbered setup rows, task rows, capability index and simple FAQ.

Mark: small original SVG of three square nodes connected by two orthogonal strokes, beside the text `design-graph`. Decorative mark is aria-hidden; wordmark link has accessible name `Design Graph home`. It must not resemble a live status indicator.

### Semantic tokens

| Token | Dark (default) | Light |
|---|---|---|
| `--bg` | `#101815` | `#F4F5EE` |
| `--surface` | `#18231E` | `#FFFFFF` |
| `--text` | `#EDF3EA` | `#16231B` |
| `--muted` | `#ADBCB0` | `#4C6254` |
| `--accent` | `#B7F36B` | `#315F18` |
| `--on-accent` | `#101815` | `#FFFFFF` |
| `--accent-hover` | `#C9FA91` | `#244A11` |
| `--border` | `#60766A` | `#73866E` |
| `--focus` | `#B7F36B` | `#315F18` |

Use muted for secondary copy, never lower-opacity text. Structural rules may use border at reduced opacity, but control boundaries, graph relationships carrying meaning and focus rings use full-strength border/focus. Links are accent and underlined in prose; no meaning conveyed only by color. CTA uses accent background/on-accent foreground. Secondary button is transparent with full border. Theme all code/diagram surfaces too; no dark-only terminal island in light mode.

Measured sRGB contrast, calculated locally using WCAG relative luminance:

| Pair | Dark | Light |
|---|---:|---:|
| text / bg | 15.99 | 14.83 |
| muted / bg | 9.11 | 6.02 |
| text / surface | 14.34 | 16.27 |
| muted / surface | 8.16 | 6.60 |
| accent / bg | 13.79 | 6.88 |
| accent / surface | 12.36 | 7.55 |
| border / bg | 3.69 | 3.57 |
| border / surface | 3.31 | 3.91 |
| on-accent / accent | 13.79 | 7.55 |

These are specified-palette checks, not a claim that an unbuilt page has passed accessibility testing. Implementation must verify rendered states, including hover/focus.

Typography: `system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`; code/labels: `ui-monospace, SFMono-Regular, Consolas, monospace`. No network font requests. Body 17px/1.6; mobile 16px/1.6. Main headline `clamp(2.5rem, 5.2vw, 4.5rem)`, weight 650–700, line-height 1.06, letter-spacing -0.045em; max 13ch. Section headline `clamp(1.875rem, 3.2vw, 2.75rem)`, line-height 1.14, -0.03em. Eyebrow 12px/1.5 monospace, 0.09em letter-spacing, uppercase. Code 13px/1.65, labels 13px/1.5; never shrink code to fit. Keep prose ≤62ch. Space scale 4/8/12/16/24/32/48/64/80/112px. Control radius 8px; panels 12px; no pill panels. Controls at least 44×44px, primary 48px high. Borders 1px; no heavy shadows.

## 3. Composition and responsive rules

Container `min(1152px, calc(100% - 2 * gutter))`; gutter 32px ≥1024, 24px 640–1023, 20px <640. Section padding 96px desktop / 64px tablet / 56px phone. Section separators are fine rules, not alternating giant rounded cards. Header non-sticky, 80px desktop; no fixed overlays. Anchors get 24px scroll margin.

Desktop ≥1024:

    header: mark/wordmark | Overview  Setup  Examples | GitHub  theme
    hero:   eyebrow + H1         | specimen heading
            description         | graph with three named nodes
            setup + GitHub      | two-line tool call / caption
            local / CLI + MCP   |
    overview: section title     | definition + audience + format list
    setup:  section heading above 01 / 02 / 03 rows, instructions left/code right
    examples: heading + scope note above four horizontal prompt/tool rows
    features: heading left, numbered six-item capability index right
    FAQ: heading left, disclosure list right
    final CTA: large headline + short body | setup + documentation
    footer: wordmark | GitHub  Documentation  PyPI

Hero top/bottom padding 80/96px, columns 1.05fr/1fr, 64px gap, aligned center. Above-fold priority at 1440×900: navigation, full headline/description, both CTAs and a legible specimen; no arbitrary full-viewport hero. Specimen about 480×400px but intrinsic, not fixed height; caption stays in flow.

640–1023: hero stacks, text then specimen; no reserved empty column. Overview and features may retain two columns when copy fits, setup and FAQ stack. Below 640: everything one column; header first row wordmark/theme, second row visible wrapping text links; no hamburger or hidden menu. Header auto-height. CTA row wraps to stacked full-width buttons. Use `min-width:0` on grid/flex children, `max-width:100%` on media. Code blocks alone can horizontally scroll, labelled and keyboard-focusable when overflowing; the document must never scroll sideways. Long code/tool identifiers can wrap outside pre blocks (`overflow-wrap:anywhere`). Graph becomes a vertical HTML flow with the same labels, no tiny desktop SVG scaled down. Mobile sections must not contain a line-art diagram wider than the viewport.

## 4. Exact public copy and section hierarchy

The following is the approved content, not placeholder prose. Source IDs refer to the claims matrix. One H1, ordered H2s; small eyebrows are paragraphs, not headings.

### Header

Wordmark `design-graph` → `#top`. Links `Overview` → `#overview`, `Setup` → `#setup`, `Examples` → `#examples`, `GitHub` → repository URL in §6. Theme button specified in §5. Skip link `Skip to content` → `#main`.

### Hero (`#top`; main has `id="main"`)

Eyebrow: `HTML PROTOTYPES → AGENT CONTEXT`

H1: `Give your agent the design context it needs.`

Body: `Turn standalone HTML prototypes into a typed knowledge graph. Query screens, components and design tokens from your terminal or through a local MCP server.` [C01, C02]

Primary: `Start local setup` → `#setup`.
Secondary: `Explore on GitHub` → repository.
Support line: `Python 3.10+ · CLI + MCP · Local graph storage` [C02, C03]

Specimen title: `From prototype to specific context`

Specimen content is a fixed, noninteractive HTML/CSS diagram with text labels:
- Input `simple.html` → `Typed graph`.
- Graph screen node `RestaurantsPage` branches to component nodes `BtnPrimary` and `SectionCard`.
- Under diagram: code `get_component(name="BtnPrimary", doc="simple")`.
- Caption always visible: `Illustrative graph based on the repository fixture. Not a live connection.` [C04]

Do not fabricate a tool response, stats panel or graph inference beyond these fixture relationships. Decorative connector geometry can be aria-hidden; the visible figure caption must include a plain-language description: `RestaurantsPage uses BtnPrimary and SectionCard.` Do not color the fixture's yellow button as an accessible UI control; this is a labeled graph, not a recreation of the fixture.

### Overview (`#overview`)

Eyebrow: `WHAT IT IS`
H2: `A queryable layer between prototype and implementation.`
Body: `Design Graph reads the structure and details in supported HTML prototypes and stores them in a Kuzu graph. Your agent can request a screen, inspect a component or look up tokens instead of reading the entire HTML file for every task.` [C01, C02]

Audience line: `For frontend developers and designers handing HTML prototypes to coding agents.` This is editorial positioning, not a compatibility claim.

Format list, with heading `Supported inputs`:
- `Single-file HTML: bundled React, Tailwind or plain HTML.`
- `DC canvas bundles containing DC pages.` [C05]

Boundary note: `Start from a supported HTML file. This is not a live design-tool connection.` Link `Read the supported formats` → README supported-prototypes anchor.

### Setup (`#setup`)

Eyebrow: `LOCAL SETUP`
H2: `Build the graph. Then choose how to query it.`
Intro: `You need Python 3.10+ and pip or pipx. An MCP client is optional if you only use the CLI.` [C03]

Use three visible numbered rows, not hidden tabs; copy buttons for every code block. Optional paths are details within their row, not mandatory extra steps.

01 — `Install Design Graph`
Body: `Install the package and check that the command is available.` [C06]
```bash
python3 -m pip install design-graph
design-graph --version
```
Small text: `Prefer isolated CLI installs? Use pipx instead of pip.`
Optional disclosed block with summary `Install with pipx`:
```bash
pipx install design-graph
```
Troubleshooting inline link `Installation options` → README install.

02 — `Build your prototype graph`
Body: `Run this with your HTML file. Replace prototype.html with its path. The default database name is the file name without .html.` [C07]
```bash
design-graph prototype.html
design-query screens
```
Note: `With multiple databases, select one explicitly:` [C08]
```bash
design-query --doc "prototype" screens
```
`prototype` is an example database name, not a generated fixture delivered by this site. Do not add a download button for a nonexistent sample.

03 — `Connect an MCP client (optional)`
Body: `The MCP server runs locally over stdio. There is no hosted server URL to paste.` [C09]
Subheading `Cursor` + text `Add this entry to ~/.cursor/mcp.json or your project's .cursor/mcp.json. Merge it into any existing configuration.`
```json
{
  "mcpServers": {
    "design-graph": {
      "command": "design-mcp"
    }
  }
}
```
Subheading `Claude Code`:
```bash
claude mcp add --scope user design-graph -- design-mcp
claude mcp get design-graph
```
Note: `Build your graph before querying it. With multiple prototypes, pass doc in a tool call or select one with set_prototype. The client must be able to find design-mcp on its PATH.` [C08, C09, C10; PATH is an operational prerequisite, not a new capability]
Link `MCP configuration details` → README configure-the-mcp-server. Do not list unverified MCP client configurations or one-click install deep links. Do not imply Claude web/Claude Desktop support from the documented Claude Code command.

### Examples (`#examples`)

Eyebrow: `ASK FOR WHAT YOU NEED`
H2: `Start with a screen. Follow the details.`
Intro: `Example prompts for a connected MCP client. The agent chooses the tools; these are not buttons that run a query. Replace fixture names with names from your own graph.` [C10, C11]

Four rows, each with `You ask`, quoted prompt, `Relevant tool` and a wrapping monospace call. No mocked assistant response.

1. `Find the starting point`
Prompt: `List the screens in my prototype.`
Tool: `list_screens()`
2. `Inspect a component`
Prompt: `Show BtnPrimary, including its props and hover state.`
Tool: `get_component(name="BtnPrimary", doc="simple")`
3. `Collect a screen's context`
Prompt: `Give me the context to implement RestaurantsPage.`
Tool: `assemble_page(name="RestaurantsPage", doc="simple")`
4. `Read the color tokens`
Prompt: `Which color tokens does this prototype use?`
Tool: `get_tokens(category="color", doc="simple")`

Scope note: `BtnPrimary, RestaurantsPage and simple are repository-fixture examples, not names every prototype contains.` Relevant tool calls are explanatory MCP notation, not shell commands. No copy button on a whole prompt+tool row; optional prompt copy copies the prompt alone, with label `Copy prompt`.

### Features (`#features`)

Eyebrow: `INSIDE THE GRAPH`
H2: `Inspect structure, style and relationships.`
Six-item numbered index, not six large identical cards:

01 `Screens and components` — `Inspect screen outlines, sections and component hierarchy.` Tool labels `get_screen · get_component` [C12]
02 `Tokens by mode` — `Query extracted color, spacing, typography and other tokens, including their modes when present.` Tool `get_tokens` [C13]
03 `Search and impact` — `Find named elements and text, then inspect who uses a component or token.` Tools `search · impact` [C14]
04 `Screen assembly` — `Request a screen's skeleton, component definitions, referenced data and tokens. Long answers are returned in parts.` Tools `assemble_page · get_full` [C15]
05 `Resources and embedded assets` — `List prototype resources and extract embedded fonts or images into your workspace.` Tools `get_resources · get_asset` [C16]
06 `Build changes and integrity` — `Review screens and components added or removed since the previous build, and check graph integrity from the CLI.` Tools `get_build_diff · design-graph validate` [C17]

Link `Read the tool reference` → README mcp-tools. Never claim complete automatic production-code generation, pixel-perfect verification or a guaranteed token/cost saving.

### FAQ (`#faq`)

Eyebrow: `BEFORE YOU START`
H2: `A few practical details.`
Native details/summary disclosures; first open by default, others closed. Multiple can stay open. All answers remain readable without JavaScript.

Q `Do I need an MCP client?`
A `No. You can build and query graphs with the CLI. Connect an MCP-compatible client only if you want an agent to use the tools.` [C03]

Q `Can I paste a hosted MCP URL?`
A `No. Design Graph exposes a local stdio server through design-mcp. The setup above shows the documented Cursor and Claude Code configurations.` [C09]

Q `Which prototypes can I use?`
A `Supported inputs are single-file HTML prototypes with bundled React, Tailwind or plain HTML, and DC canvas bundles containing DC pages. Check the supported formats before building your graph.` [C05; include supported-formats link]

Q `What if I have more than one prototype?`
A `Each HTML file gets its own database by default. Select a database with --doc in the CLI, or pass doc to an MCP tool call. Use --db when same-named HTML files need separate databases.` [C07, C08, C10]

Q `Does validation prove the implementation matches visually?`
A `No. Graph validation checks integrity. The MCP component-implementation check is best-effort and cannot fully verify stylesheet or utility-class styling. Review the rendered implementation separately.` [C18]

Q `Do I need to rebuild after editing the HTML?`
A `Yes. Run design-graph on the HTML file again. Unchanged files are skipped unless you use --force. The MCP server detects rebuilt databases; reconnect after changing its graph-directory configuration or upgrading the package.` [C07, C19]

### Final CTA (`#start`)

H2: `Bring your prototype into the conversation.`
Body: `Install Design Graph, build a local graph and ask for the context your next UI task needs.` [C01, C06, C07]
Primary `Start local setup` → `#setup`.
Secondary `Read the documentation` → repository README.

Footer links: `GitHub`, `Documentation`, `PyPI`. No sign-up, pricing, unverifiable social proof, version badge, installation-time promise or legal/privacy page that does not exist. Do not hardcode a product version; docs describe baseline source, not tested parity of every PyPI release.

Metadata: title `Design Graph — HTML prototypes as agent context`; description `Turn supported HTML prototypes into a typed knowledge graph. Query screens, components and design tokens with a CLI or local MCP server.` `lang="en"`. No invented social image; if adding one, use an original local SVG/PNG, never a remote hotlink. Canonical only final contracted URL, not a scratch/preview address.

## 5. Interaction and accessibility contract

- Default is dark regardless of OS. Theme button is explicit text+optional decorative sun/moon: `Light theme` in dark / `Dark theme` in light, accessible name `Switch to light theme` / `Switch to dark theme`. Persist `design-graph-theme` with value `light` or `dark` in localStorage; validate value; wrap read/write in try/catch. Apply a valid saved theme before first paint where possible. Blocked storage must not break rendering or the toggle. Add `color-scheme` per theme. Do not use an ambiguous icon-only switch.
- No JS: dark content, navigation, command selection and FAQ work. Hide inert copy/theme buttons until enhanced; add noscript text `JavaScript enables the theme switch and copy buttons. Commands can still be selected manually.`
- Copy: `Copy command` / `Copy configuration` with contextual accessible label (e.g. `Copy Cursor configuration`). On success text `Copied`, announce `Copied to clipboard.` in one polite live region; reset after 2 seconds. Copy exact raw block only, no `$`, line numbers or labels. On clipboard failure, show `Copy unavailable. Select and copy the code manually.` Never report success before resolved clipboard write. Keep focus on button; keep widths stable. No insecure fallback that edits a user's document.
- Use native buttons for actions, links for navigation, native details for FAQ. No clickable entire card, tab/carousel or modal. All visible controls work with keyboard. Focus: 3px solid focus outline, offset 3px; keep rings clear of overflow clipping. Skip link visible on focus. Prose links underlined; buttons have real boundaries.
- Theme and hover transitions color/background/border only, 140ms ease-out. No initial animation or smooth scrolling required; no moving/pulsing graph. `prefers-reduced-motion:reduce` disables transitions and any optional smooth scroll. Never animate height of FAQ.
- Text resizing and 200% zoom reflow; 320px minimum viewport check. Test phone landscape as well as portrait. Footer and code lines cannot force viewport overflow. At 400% zoom on a 1280px viewport, single-column content remains usable.
- External links open same tab, no surprise new windows; no query parameters/tracking. SVG decoration hidden from accessibility tree. Diagram's meaningful labels and caption remain text, not outlined glyphs or canvas. Body hierarchy has header/nav/main/section/footer landmarks and unique IDs.

## 6. Navigation registry (exact hrefs)

Repository: `https://github.com/manorfm/design-graph`
Documentation: `https://github.com/manorfm/design-graph/blob/main/README.md`
Supported formats: `https://github.com/manorfm/design-graph#supported-prototypes`
Installation options: `https://github.com/manorfm/design-graph#install`
MCP configuration: `https://github.com/manorfm/design-graph#configure-the-mcp-server`
Tool reference: `https://github.com/manorfm/design-graph#mcp-tools`
Package: `https://pypi.org/project/design-graph/`
Final canonical: `https://manorfm.github.io/design-graph/` (target for later publication, not yet published or a CTA).

Internal fragments: `#top`, `#main`, `#overview`, `#setup`, `#examples`, `#features`, `#faq`, `#start`. Do not substitute empty `href="#"` links or send setup actions to the future Pages URL. README links deliberately follow main for current documentation; source audit is pinned separately.

## 7. Implementation handoff and review acceptance

Dev creates `pages/landing` in a separate worktree from this UX commit, preserving these two documents. Do not implement the page in this UX phase. No external publication or production credentials. Add a reproducible local-serving procedure that really exercises `/design-graph/` rather than only `/`; test exact static export of `site/` to an isolated directory, not a push. All assets self-hosted; no fetched fonts/icons/scripts. No changes to MCP/CLI to make landing copy true.

Post-implementation UX/QA must record actual browser execution and screenshots at 1440×900, 768×1024, 390×844 and 320×800 in both themes; do not claim screenshots from wireframes. Inspect at 200% zoom, keyboard-only and reduced motion. Acceptance:

1. H1, proposition, setup CTA and clearly illustrative specimen establish the product, without dashboards or false live results; dark default is visibly forest/cream/lime, not neutral template chrome.
2. All seven required sections appear in the specified order; copy/source matrix has no invented capabilities, numerical ROI, client support, pricing or claims of pixel-perfect validation.
3. Exact command/config strings match this spec and pinned source; installation/build/MCP are distinct, MCP optional, no hosted URL substitution. Every copy button returns the exact block and reports success/failure honestly.
4. Setup and examples readable at phone widths; no document horizontal overflow (`scrollWidth <= clientWidth`, allowing only labelled code-block scroll). Specimen is legible vertical flow on narrow screens. Navigation is visible, never a nonworking menu.
5. Theme survives reload, invalid/blocked storage doesn't crash; no-JS content and FAQ remain usable. Both themes have AA text contrast and visible 3:1 control/focus boundaries; measure rendered states, not just these tokens.
6. All links and fragment targets resolve, local assets load beneath `/design-graph/`, canonical isn't treated as an already-live service. Test GitHub anchors against source heading IDs; no placeholder links or accidental root paths.
7. Full keyboard path, skip link, focus visibility, FAQ semantics, accessible copy feedback and readable text reflow pass. Theme switch does not steal focus or change scroll position. Reduced motion has no animated diagram or forced smooth scroll.
8. Serve/export static output works without build/network assets and does not alter runtime tests. Report browser/tool versions and executed results separately from inherited Infra pytest evidence.

No visual prototype or rendered-page audit is claimed by this document. It is a complete content/layout/state contract; the downstream cards implement and verify it.
