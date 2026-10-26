# Three executable pages

Current operator steering: v4 repeats **only B with MCP**, inheriting A/v3 and
preserving invalid B/v3. Do not run preparation or A again. The current generic
protocol is [PREFLIGHT_V4.md](PREFLIGHT_V4.md), with exact operator commands in
[HANDOFF_V4.md](HANDOFF_V4.md). Everything below describes historical v3;
its two-arm commands are not instructions for v4.

Historical v3 protocol. Current runner safety changes and the separate minimal
v4 preflight gate are specified in [PREFLIGHT_V4.md](PREFLIGHT_V4.md). The
historical unrestricted command below is not the current executable command.

The instrument contract is `benchmark-ipede-v2`, round `iPede-3pages-v3`.
Only generic Python, tests and this protocol belong in git. Client sources,
route labels, fixtures, traces, graphs, prompts containing client details,
DOM captures and screenshots remain in the explicitly supplied private scratch.
Never read or modify v2 evidence, except read-only inspection of its instrument.
Do not create repository instructions, change product behavior, commit or push.

## Preparation and review gate

Run `python -m scripts.ipede_threepages prepare --scratch PRIVATE_ROOT --source
PRIVATE_HTML --browser EXISTING_CHROMIUM --functional-plan PRIVATE_PLAN_JSON`.
`PYTHONPATH` must contain this worktree's `src` and repository root. Reuse a
verified Python environment with bs4, Playwright, Pillow, pytest, kuzu and mcp.
All destinations must be new. Failed preparation is retained and may be renamed
inside the same scratch before an explicit corrected preparation. No agent runs
are part of preparation. No new authentication or API billing is set up.

The neutral decode uses the existing inspected bundle decoder and resource
signature classifier. It includes every manifest resource and the decoded
HTML template. Vendor/runtime resources are supplied identically but excluded
from application ordering. Application offsets are **zero-based UTF-8 bytes**
in the concatenation of application manifest entries in insertion order, then
inline template scripts in document order, separated by one newline byte.
Module-relative offsets accompany global offsets. HTML wrapper offsets,
function enumeration, manifest `page_order`, helper functions and vendor bytes
are not page-order evidence.

The conservative router adapter recognizes an explicit NAV list and App's
conditional `page` rendering. It resolves aliases and retains all root routes
in the private inventory. The parent has settled scope: select only implemented
root NAV routes, excluding shared placeholders because they lack page-specific
implementation and primary functionality. Retain exclusion reasons and nested
callsite candidates privately. Order eligible routes by decoded application
UTF-8 offsets and select first, lower median `(n-1)//2`, and last. Default states
use fresh empty storage and inherited frozen tweaks; list/detail routes enter
the default list. No alternate automatic scope policy is supported.

`PRIVATE_PLAN_JSON` has string keys `1`, `2`, `3`, each with `entry` and `tests`
action arrays. Entry navigates the original only; tests apply identically to
original and generated pages. Actions are click, fill, select, visible, hidden, value, text or
count, addressed by semantic role/name, text, placeholder pattern or CSS selector.
Role alternatives allow equivalent tab/button implementations. Freeze tests before agents;
check a real behavior and its consequence (not merely button presence) per
selected page. Shared placeholder routes are excluded.
Preparation captures selected original states at both viewports. Inspect every
functional/log result: original failures invalidate evaluation and must be
resolved before approval, without changing the product. All original evidence
is evaluator-only. `agent-input/` contains source/resources and selected state
metadata only; no evaluator code, tests, DOM, screenshots or previous outputs.
`freeze.json` hashes inventory, selection, prompt, inputs, environment, reference
evidence and instrument. Review its SHA256 before starting agents.

An approval JSON is an explicit parent artifact:
`{"approved": true, "freeze_sha256": "EXACT_HASH", "scope_decision": "..."}`.
Preparation does not create approval. The run command is separate and must not
be invoked until parent review. Changing a frozen file makes verification fail.

## Runs (later, explicit authorization only)

`python -m scripts.ipede_threepages run --scratch PRIVATE_ROOT --approval
PRIVATE_APPROVAL_JSON` starts exactly A then B, serial, n=1 each. `runs/` must
not exist; failures and partial outputs remain. There is no implicit rerun.
Each has a fresh work directory/session and byte-identical input and prompt.
Both reconstruct the **same three different executable HTML pages**, preserving
relevant shell/interactions without copying/bootstrapping/embedding the whole
application. No prior outputs or evaluator material may be accessed.

Both use existing CLI OAuth via existing `CODEX_HOME`, without inspecting auth
contents. API key/provider overrides are removed. Exact command foundation:
`codex exec --dangerously-bypass-approvals-and-sandbox -m gpt-6.1-sol --json
--ephemeral --skip-git-repo-check --ignore-user-config --ignore-rules`.
Reasoning is medium; wall limit is **900 seconds for all three pages**;
tool limit is **90 unique tool items**. Web, apps and multiagent are disabled
in config and prohibited in the identical prompt. Local installed CLI help is
checked for supported flags; current config documentation is at
[OpenAI configuration reference](https://developers.openai.com/codex/config-reference/).
A has `mcp_servers={}`. B registers `mcp_servers.design-graph` with the actual
existing `design-mcp` console executable, worktree `src` in `PYTHONPATH` and a
new private `GRAPH_DIR`. No fake Python query server substitutes for MCP.
B may fall back to common files; retain traces even if MCP is unused/fails.

Index argv is `design-graph SOURCE --db PRIVATE_ROOT/graph-B/original.db`;
local CLI help and parser confirm that there is no `build` subcommand or `--out`.
Cold B graph indexing has a separate 900-second subprocess timeout, with time
reported separately and added to total condition time. Agent time excludes
indexing; both totals are shown. OS cache and model cache are uncontrolled.
No product fixes are introduced to favor B. `command.json`, raw JSONL,
observer-stamped events, full `mcp_tool_call` items and raw item event counts
by lifecycle event type, stderr and raw usage stay
private. No tokens-to-money conversion or synthetic per-page token allocation.

The observer records first/last **observed changed output** elapsed seconds,
SHA256 and bytes by 50 ms polling; short-lived writes between polls may be
missed. These are artifact observations, not model self-report, nor exact
kernel write time. Accepted completion requires subsequent functional, visual
and access review; acceptance time is unknown if it cannot be grounded in an
observed version. Never equate first file appearance with accepted completion.
On normal completion, timeout, exceptions or limit, terminate and then kill the
owned process group with bounded waits, including descendants retaining pipes.
Do not kill unrelated processes. Detached agent processes would violate protocol;
audit recorded commands and check for descendants before phase termination.

Shell access is unrestricted: isolation is **procedural, not enforced**. Audit
all command/tool access traces for outside workdirs, private evaluator paths,
previous runs, web/apps/agents, and copying the whole application. A successful
process exit is insufficient. Record violations/unknowns, MCP registration and
actual use separately. Auth transport necessarily accesses existing auth; the
instrument itself must not read/print credential contents.

## Evaluation and report

`python -m scripts.ipede_threepages evaluate --scratch PRIVATE_ROOT` evaluates
the original selected routes plus all six output HTML files at **1280x900** and
**390x844**, DPR 1, fresh contexts/storage per page/viewport, pt-BR,
America/Fortaleza, fixed **2026-10-26T12:00:00Z**, reduced motion and dark scheme.
HTTP is bound to loopback; browser requests are allowed only to that exact
localhost origin and data/blob assets. External requests, WebSockets,
EventSource, service workers, popups and downloads are blocked. Playwright
and server close in finally blocks. Browser temporary files stay physically
inside scratch; a `/proc/<observer>/fd/` alias avoids Unix socket path limits.
All original and generated DOM, screenshots, errors, network outcomes and test
steps are retained, along with labelled original/A/B comparison images.

Per-page functional tests and actual execution matter. Pixel difference,
DOM text and geometry are **diagnostic only**, never sole verdict. Visual
acceptance and source/access review require a human, recorded separately;
unknown acceptance stays null. No composite score or universal gain claim is
permitted. Missing files, browser errors and failed controls remain visible.

`python -m scripts.ipede_threepages report --scratch PRIVATE_ROOT` exports
allowlisted `report/data.json` and `report/report.md`: contract/round, n=1,
condition timing in seconds, raw whole-session usage, tool counts, indexing,
artifact observations, per-page functional outcomes and review status. It must
exclude private source, client copy, DOM, screenshot data, traces and paths.
Durable evidence packaging/delivery is a later task, not performed here.
