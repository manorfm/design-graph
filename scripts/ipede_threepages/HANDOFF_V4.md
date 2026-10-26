# TL handoff: neutral preflight, then B-only repetition

The operator's latest steering supersedes the historical v4 new-pair proposal.
Preserve A/v3 and the invalid B/v3. Repeat only B with the same three pages,
source, prepared selection, base prompt, model and limits. Extraction/copying
of relevant source is not reclassified as independent reconstruction.

Required environment variables in the following commands:

- `IPEDE_PY`: absolute path to the existing Python environment, retaining its
  virtualenv symlink spelling (do not resolve it to the base interpreter).
- `V3`: existing private baseline root, read-only.
- `V4`: separate user-owned private scratch root; do not reuse an attempt.

From the card worktree:

```sh
PYTHONPATH="$PWD:$PWD/src" "$IPEDE_PY" -m scripts.ipede_threepages preflight --scratch "$V4" --python "$IPEDE_PY"
```

Review `preflight-v4/gate.json`, the actual initialize/tools/list/tools/call
transcript, the catalogue, matching native completed event and neutral heading
from a useful non-listing read. The recorder forwards bytes to the real
installed server; it neither answers MCP nor makes its own requests.
Missing native evidence, failure or refusal stops the procedure. Never relax
policies, use another API for a refused action, or silently collect without MCP.

Only after successful review:

```sh
PYTHONPATH="$PWD:$PWD/src" "$IPEDE_PY" -m scripts.ipede_threepages run-b-v4 --baseline "$V3" --scratch "$V4" --python "$IPEDE_PY"
```

B revalidates the exact identity/evidence gate, indexes the integral original,
and asserts that the current-model graph contains all selected nonempty
screens before starting its new session. This setup-only read assertion is
not treatment evidence: B must still complete useful native MCP queries for
all three screens before observed output. Missing queries, early output,
refusal or missing HTML invalidates the attempt; no silent fallback or rerun.

Main `seconds` measure the executor session after indexing/readiness.
`setup_index_seconds`, `readiness_seconds`, `supervision_seconds` and
`postprocessing_seconds` are separate. Observer timing is reactive (50 ms),
not interception or accepted-page timing. `valid=true` is protocol completion,
not visual/functional acceptance or evidence of a causal improvement.

Keep raw private logs, source, graphs and screenshots out of git. Historical
v3 `evaluate`/`posthoc` commands must not relabel B/v3 as valid or process this
new root as a contemporaneous pair. Compare original/A-preserved/B-corrected
at 1280x900 and 390x844, explicitly documenting noncontemporaneous repetition,
extraction, inherited source limitations, aggregate usage and unavailable
per-call context metrics. Handoff sanitized `report.md` and `data.json` under
`benchmark-ipede-v2` to the existing landing/QA cards; no new cards.

`REVIEW_FREEZE_V4.json` records reviewed instrument/test hashes, excluding
itself and bytecode. Final runtime proof is bound again by preflight identity.
No instrument changes are permitted between successful preflight and B.
Inherited MCP registrations are explicitly disabled per name while keeping
loaded policies/rules/OAuth; there are no bypass or ignore-rules flags.
