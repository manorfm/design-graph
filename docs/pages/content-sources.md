# Design Graph — content sources and claims audit

## Provenance and boundaries

All repository line references below were read directly in the UX worktree at source baseline `ebdbeb24323d7143e0186622a7389b963e5ed350`. The UX commit adds documentation only; no source evidence files are modified. Link template for a durable source citation:

`https://github.com/manorfm/design-graph/blob/ebdbeb24323d7143e0186622a7389b963e5ed350/<file>#L<start>-L<end>`

Canonical clone: `/home/manoelmedeiros/Workspace/design-graph`. UX branch: `pages/design-direction`. The downstream dev must branch from the UX documentation commit, not from main. No DESIGN.md, AGENTS.md or .hermes.md exists in this baseline or the examined worktree ancestors. No `site/` or `docs/pages/` paths existed before this card, so these additions do not overwrite another landing or spec.

Upstream evidence: Infra card `t_12711f37`, durable attachment `/home/manoelmedeiros/.hermes/kanban/attachments/t_12711f37/infra-handoff.md` and evidence archive on that card. Infra reports a real editable-source CLI/MCP fixture smoke and `2642 passed, 7 skipped` from root pytest. Those results are inherited evidence, NOT a UX rerun, not PyPI distribution testing, not browser verification, and not a business metric. The landing must not turn them into a marketing badge.

## Claims matrix

Each ID is cited by the exact public copy in `design-spec.md`. Marketing phrasing is a narrow paraphrase of the named evidence; no inference of unsupported integrations is permitted.

| ID | Approved claim / locations | File and lines at baseline | Evidence and explicit limit |
|---|---|---|---|
| C01 | HTML prototypes become a typed Kuzu graph; overview and hero | `README.md:9-20,30-32` | Stores/queryable design vocabulary. Do not call it a hosted SaaS, generic live design-tool connection or arbitrary multi-file application parser. |
| C02 | Query screen/component/token context through CLI or MCP; request scoped context | `README.md:9-11,65-69,316-345,403-429`; `pyproject.toml:19-23` | Actual entrypoints and tool catalogue. No numeric cost, latency, time-to-install, context savings or universal performance promise. H1 is editorial proposition, not a quantitative result. |
| C03 | Python 3.10+, pip/pipx; MCP client optional for CLI; local storage | `README.md:36-42,148-158,292-309`; `pyproject.toml:10,13-17` | Kuzu database stored on local filesystem; dependency install is not an offline/no-network guarantee. No OS support matrix is claimed. |
| C04 | Example nodes and component relationship; hover/props prompt | `tests/fixtures/simple.html:5-39`; `README.md:411`; `src/design_graph/interface/mcp/tool_definitions.py:139-156` | RestaurantsPage renders BtnPrimary and SectionCard. BtnPrimary has label prop and mouse-enter/leave color changes. Graph is an illustrative depiction of fixture relationships, not a screenshot, live connection or captured response. |
| C05 | Single-file bundled React/Tailwind/plain HTML; DC canvas bundles | `README.md:13-20` | Preserve the format restrictions. Mention of React does not imply support for arbitrary React repositories. Do not replace DC canvas with Figma. |
| C06 | Install and verify; optional pipx | `README.md:44-78`; `pyproject.toml:19-23` | Exact strings: `python3 -m pip install design-graph`, `design-graph --version`, `pipx install design-graph`. Source documents PyPI install; Infra did not separately verify a registry-installed release. Do not promise installed release equals unreleased main. |
| C07 | Build graph, per-file default database, incremental rebuild, same-stem boundary | `README.md:148-196` | `design-graph prototype.html`; default prototype.db. `--force` bypasses unchanged hash; `--db` separates same-stem filenames. No live file watcher or auto-build is claimed. |
| C08 | CLI screens and explicit selection for multiple DBs | `README.md:217,258,316-345` | `design-query screens`; `design-query --doc "prototype" screens` combines documented syntax and the default name from C07. It is an example path/name substitution, not a new flag. |
| C09 | Local stdio setup in Cursor / Claude Code | `README.md:349-399` | Exact mcpServers JSON command design-mcp; user/project Cursor file paths and `claude mcp add --scope user design-graph -- design-mcp`, `claude mcp get design-graph`. No HTTPS MCP endpoint, OAuth/account flow, web connector, Claude Desktop or other client install command is claimed. PATH visibility is required to execute a command by name. |
| C10 | Prototype names, doc argument and selection | `README.md:433-449`; `src/design_graph/interface/mcp/tool_definitions.py:11-18,323-339` | doc is the DB filename without .db. set_prototype is connection-scoped and resets on reconnect; not durable task context. list_screens reports documents/screens. |
| C11 | Four sample prompts map to real tools and arguments | `src/design_graph/interface/mcp/tool_definitions.py:21-61,96-115,139-156`; `tests/fixtures/simple.html:5-39`; `README.md:407-413` | See exact mapping below. Prompts express user intent, not guaranteed tool invocation or output. MCP call notation is not runnable shell. |
| C12 | Screen outline/sections and component hierarchy | `README.md:408,411`; `src/design_graph/interface/mcp/tool_definitions.py:117-156` | get_screen/get_component. Extracted prototype state is not proof of production behavior. |
| C13 | Tokens, categories, modes when present | `README.md:413,423`; `src/design_graph/interface/mcp/tool_definitions.py:27-61` | get_tokens. Do not imply every prototype defines modes or a complete semantic design system. |
| C14 | Search and relationship impact | `README.md:416-417`; `src/design_graph/interface/mcp/tool_definitions.py:63-95` | search finds names/text; impact traces uses/reach. Not a guarantee that changing source updates all consumers or a production dependency scanner. |
| C15 | Screen skeleton, component definitions, referenced data, tokens; long answer recovery | `README.md:409,412,429-431`; `src/design_graph/interface/mcp/tool_definitions.py:96-115,159-178` | assemble_page and get_full. 'Context to implement' is retrieval, not an automatic production-code export. |
| C16 | Resource listing and embedded font/image extraction into workspace | `README.md:414-415`; `src/design_graph/interface/mcp/tool_definitions.py:180-213` | get_resources lists, get_asset writes embedded files. Do not claim it downloads all externally hosted assets or grants asset licenses. |
| C17 | Latest-build added/removed screens/components; CLI graph integrity | `README.md:222-231,418`; `src/design_graph/interface/mcp/tool_definitions.py:284-299` | get_build_diff reflects the last actual build, not live source edits. design-graph validate is a separate CLI operation. Avoid claiming style-level diff for all properties. |
| C18 | Validation is not visual proof | `README.md:222-231,419,427`; `src/design_graph/interface/mcp/tool_definitions.py:300-320` | Graph integrity differs from MCP best-effort implementation checking; stylesheet/utility-class gaps and pixel-perfect limitation must remain explicit. |
| C19 | Rebuilt DB reload; reconnect after config/upgrade | `README.md:182,399`; `README.md:94-97` | HTML edits require manual rebuild. Server reload checks file mtimes on calls. Model-changing package upgrades may require `design-graph --force <prototype.html>`; FAQ is concise, full upgrade caveat stays in README. |

## Prompt-to-tool mapping (not output fixtures)

| Public prompt | Relevant call | Grounding |
|---|---|---|
| List the screens in my prototype. | `list_screens()` | Definitions lines 21-25: no parameters. |
| Show BtnPrimary, including its props and hover state. | `get_component(name="BtnPrimary", doc="simple")` | Definitions lines 139-156; fixture lines 5-15. |
| Give me the context to implement RestaurantsPage. | `assemble_page(name="RestaurantsPage", doc="simple")` | Definitions lines 96-115; fixture lines 25-39. |
| Which color tokens does this prototype use? | `get_tokens(category="color", doc="simple")` | Definitions lines 27-61; README line 423; fixture contains literal colors. |

The name `simple` assumes building `tests/fixtures/simple.html` without renaming the database; public setup instead uses the reader's `prototype.html`. The page must explicitly explain the difference and never imply setup automatically creates the named sample. No real tool response is fabricated or embedded.

## Exact copy-block inventory

Downstream tests should compare these six blocks with the public setup, preserving quotes, braces and flags:

1. pip: `python3 -m pip install design-graph` then `design-graph --version` (README 49,74).
2. pipx alternative: `pipx install design-graph` (README 55).
3. Build/query: `design-graph prototype.html` then `design-query screens` (README 151,319).
4. Explicit document: `design-query --doc "prototype" screens` (README 320 uses app-v1, replaced with the documented default stem of prototype.html).
5. Cursor configuration JSON (README 357-365); merge into existing configuration, never instruct blind overwrite.
6. Claude Code: `claude mcp add --scope user design-graph -- design-mcp` then `claude mcp get design-graph` (README 372-373).

Inventory count is six setup blocks (one JSON and five shell blocks). No additional installation commands should be invented. FAQ inline --force/--db are explanatory documented flags, not extra copied blocks.

## CTA / link evidence

Repository and README hrefs identify the actual source repository, not an external service:

- `https://github.com/manorfm/design-graph` — actual clone remote identity.
- `https://github.com/manorfm/design-graph/blob/main/README.md` — file exists in baseline; live docs intentionally follow main.
- Repository README anchors `#supported-prototypes`, `#install`, `#configure-the-mcp-server`, `#mcp-tools` — literal matching headings at README lines 13,44,349,403.
- `https://pypi.org/project/design-graph/` — README badge link line 7 and installation instructions lines 44-56; this is not a pin to source-baseline version.
- `https://manorfm.github.io/design-graph/` — task's final publication contract only. Infra recorded Pages/gh-pages absent. Do not describe as live until TL publishes and reads back the deployed target.
- Setup CTA is local `#setup`, not an executable install link. All fragments in the spec are required unique IDs.

No pricing, sign-in, trial, issue template, downloads, hosted MCP endpoints or client logos are needed. Keeping the CTA local avoids a nonexistent hosted install flow.

## Reference observation

Consulted `https://taplio.com/taplio-linkedin-mcp` with web_extract in this UX run. Text extraction succeeded; full extracted page was saved by the retrieval tool. No screenshot or visual resemblance is claimed.

Observed structure in the successful text extraction: product navigation, MCP explanation, copyable connection setup, tools grouped by purpose, conversational examples, deeper workflows, FAQ and closing CTA. Use only its reading cadence. Design Graph differs: local install/build before optional stdio setup, no account flow, no hosted URL, no compatibility-logo strip, no time/ROI metric, no borrowed comparison claims.

## Deliberately excluded statements

- README token-range examples, package-description cost wording or benchmark results are not comparative landing metrics.
- Supported init-skill tools (README 264-288) are not a universal MCP-client compatibility table. No unsupported client setup is presented.
- Best-effort implementation validation is not pixel-perfect validation or automatic code migration.
- get_build_diff is last-build structural change retrieval, not a live sync service.
- Resource listing is not automatic download of arbitrary third-party assets.
- Local graph storage is not a blanket security/privacy/no-telemetry guarantee for every dependency or MCP client.
- No visual/browser/AA conformance result exists yet. Palette ratios in the design spec are computed specifications, to be checked against rendered output later.

## Handoff evidence boundary

UX deliverable is the two committed documents, not a runnable landing. The complete public copy, layout rules, token contrasts, interaction states and browser-review checklist are in design-spec.md. Infra owns runtime-source tests already executed; dev owns static implementation and real smoke tests; following UX/QA cards own rendered review. No publication, preview upload, remote push or main modification was performed in this phase.
