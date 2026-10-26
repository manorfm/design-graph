# v4 B-only protocol and native preflight

Operator steering supersedes the historical two-arm v3 experiment in
[PROTOCOL.md](PROTOCOL.md). Run only B with native design-graph MCP. Existing
A/v3 is inherited evidence; old B/v3 remains invalid. Neither historical lane,
preparation, freeze nor executor files are rewritten. No new A is authorized.

Use `preflight --scratch NEW_V4_ROOT --python EXISTING_VENV_PYTHON` after
review, inspect its proof, then `run-b-v4 --baseline EXISTING_V3_ROOT --scratch
NEW_V4_ROOT --python EXISTING_VENV_PYTHON` once. Both roots must already exist;
the v4 root must be separate from the v3 tree. No collection or real preflight
is part of implementation/testing. Exact operator commands are in
[HANDOFF_V4.md](HANDOFF_V4.md).

The baseline preparation is verified against **all frozen file manifest
entries**, including original integral HTML, selection offsets, states, source,
resources, prompt and evaluator evidence. Unexpected preparation files also
fail verification. Historical instrument hashes are retained as provenance;
they are never checked against the changed v4 instrument. `agent-input/` and
the base `prompt.txt` are copied byte for byte into the B lane. The only prompt
appendix is CONDITION B: useful native MCP read queries for each selected
screen before any page output, stopping invalid if that cannot be done.
Extraction/copying of relevant supplied source is permitted by operator
steering and the baseline task; no independent reconstruction restriction is
added. Model, medium reasoning, 900-second and 90-tool limits, original selected
screens/states and full common source remain the baseline values.

Before any indexer or agent is launched, B revalidates successful preflight,
its identity and every evidence hash. It then records provenance hashes for
preparation, historical instrument, inherited A evidence/output and available
historical results. It indexes the **integral frozen original.html**, using
`design-graph ORIGINAL --db GRAPH/original.db`, before starting B's session.
Read-only setup assertions verify the current graph model and all three
nonempty selected screens, closing their database handles before the session.
This is not a substitute for native B queries. Setup/index and readiness time
are separate from the main executor session time. Process
cleanup and final audit/postprocessing are reported separately; these do not
inflate main time. Functional acceptance remains evaluator work; output
observations alone never establish accepted pages.

Preflight uses a self-authored neutral fixture and the same executor command,
model, limits, sandbox and transparent stdio proxy as B; only attempt paths
change. It never reads product input or launches A/B. The recorder forwards
original bytes unchanged to/from the installed `design-mcp`; it implements no
MCP responses and sends no requests itself. The model must discover the tools
and issue a useful non-listing read query returning the neutral heading.
The proof contains initialize/initialized,
complete tools/list pagination, tools/call request/results, raw native executor
JSONL, observer times, both stderr logs, metrics and exact invocation.
A completed native MCP event must match the real request's tool, arguments
and response content. Missing handshake, catalogue, completed turn, successful
matching call, nonzero exit, timeout, guard refusal or changed evidence fails.

B additionally requires three relevant successful calls from the discovered
catalogue, matched independently to native completed events and actual RPC
responses. Queries must explicitly target each selected key/label/component
using `name` or `screen`. Supported useful reads are `get_screen`,
`assemble_page`, `get_component`, `get_full`, and screen-scoped `get_tokens`.
Listing/discovery/global queries do not count. Results must include a selected
screen identifier and substantive source/design content (at least 80 characters
and component/section/style/token/source evidence); diagnostic/error/echo-only
results do not count. This is a conservative mechanical relevance check;
manual review of the retained content remains appropriate.

The live observer checks before accepting newly received native completions
and at 50 ms polling resolution. Any file/directory observed under `output/`
before coverage is complete terminates the process group and invalidates B.
This is observational supervision, not filesystem write interception: extremely
brief writes between polls and actions batched before a refusal is observable
cannot be ruled out. Missing even one screen invalidates B, including a clean
executor exit with generated pages. There is no silent source-only fallback,
retry, alternate executor or alternative API after a guard refusal. The raw
result, provenance, index log and partial work are retained on failure.

# Configuration and review freeze

Use `workspace-write` and inherited policies. Never use sandbox/approval bypass
or `--ignore-rules`. The safest isolation here is explicit per-server
`enabled=false` overrides for all MCP names discovered in inherited user and
ancestor project TOML (including profile tables), followed by enabling
only the proxy-backed `design-graph` server. The original config stays loaded
and unmodified, preserving policy and provider settings. `--ignore-user-config`
would keep execpolicy rules but remove other policy-related config; it is not
used. If managed requirements prevent this setup, stop and retain the refusal.
Apps, web and multi-agent features remain disabled.

Existing CODEX_HOME OAuth is used without reading credential contents; API key
and provider environment overrides are removed. No global config, credential,
product/source or site file is modified. Local configuration/rules/instruction
hashes are bound to the gate, not copied as contents. The identity includes
actual proxy command/arguments (recorder, transcript/stderr paths and installed
server), venv interpreter spelling **without resolving its executable symlink**,
launcher and real native executor binary hashes, Node/server/indexer hashes,
explicit command/model/limits, instrument and worktree source hashes. Attempt
paths are normalized. Unidentifiable native binary layouts fail closed.
External backend or managed policy changes are not fully attested locally.

`REVIEW_FREEZE_V4.json` records the reviewed instrument/test/document hashes.
After successful preflight, make no instrument changes before the one B run.
The successful gate additionally binds the runtime identity and proof. Any
instrument/runtime drift rejects B before launch; do not rerun preflight to
work around a refusal. The historical `run`, evaluation and report commands
remain for historical evidence and must not be used for this B-only round.
The v4 result is `run-results-v4.private.json`, with inherited A provenance and
B validity/timing; historical v3 report labels are not reused as a v4 result.

Technical bootstrap failures before any model session may be diagnosed and
corrected in the instrument, preserving the failed attempt and using a distinct
scratch root for a new preflight. This never authorizes bypassing a guard or
repeating measured B for a better result. CLI dotted keys use validated bare
server names: JSON quoting a path segment creates a different incomplete MCP
record in this executor version rather than overriding the inherited server.
