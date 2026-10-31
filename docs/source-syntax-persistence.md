# Qualified source-syntax persistence

`model.graph.source_syntax_context` appends a closed **source-syntax-context/1**
JSON envelope to the existing three-column `BindingContextSnapshot` table
(`binding-context-kuzu/1`). No syntax-specific columns or edges are added.
Existing `binding-context/2`, `binding-capture/3`, pipeline and source-syntax
producer contracts remain unchanged. Missing extension is unknown; crossing
logical formats explicitly fails rather than upgrading legacy facts.

Create `SourceSyntaxSnapshot.create(SourceInventory(snapshot, input_artifact,
units), captures)` from explicit `source-syntax-capture/1` captures. `snapshot`
is a caller-selected 64-lowercase-hex immutable identity, **not** the payload
digest. `units` is the exact ordered captured inventory (maximum 16), not a
claim that all scripts in a document were captured. Inventory retains each
unit's locator, source hash, source type, syntax and syntax producer fingerprint.
`write_source_syntax(connection, snapshot)` owns a transaction and uses CREATE,
never MERGE/upsert. Any reused identity, even with identical bytes, refuses and
rolls back. Handles belong to the caller; close both in finally.

`read_source_syntax` admits all units on every invocation. The stored envelope
carries a canonical SHA256 over the typed snapshot; this catches inconsistent
mutations, not coherent malicious rewrites. `expected_sha256=snapshot.digest()`
can check an independently retained trusted capture-custody anchor. An anchor
read from the same mutable database authenticates nothing. A coherent rewritten
source/capture/inventory with its own recomputed digest can pass unanchored;
source-to-AST derivation and omissions are not self-authenticating.

Public `read_project_source_syntax` requires snapshot, input artifact, exact
inventory, qualified unit and member-use ID. No caller-supplied checked handle,
validation flag or cache bypass exists. The result carries source hashes and
producer fingerprints, custody status, unresolved alternatives, and
`runtime_claim=false`. `source_payload_ownership` remains **unknown**: this
snapshot does not bind current LEGACY graph source payloads to its inventory.
R1's automatic-source withholding guard is unchanged. Enabling automatic legacy
association requires a separate fresh BUILD receipt committing current general
graph source payloads, whole inventory and snapshot; existing key/edge receipts
are insufficient. Assembly, MCP delivery and R13 closure are not implemented.

Normal read-only command (repeat `--inventory-unit` in inventory order):

```sh
design-query source-candidate --db /absolute/owned.kuzu \
  --snapshot HEX_ID --input-artifact INPUT \
  --inventory-unit UNIT_A --inventory-unit UNIT_B \
  --unit UNIT_B --use u1 --expected-sha256 TRUSTED_CAPTURE_DIGEST
```

No Node, capture, pipeline or parser import is needed by product read modules.
Kuzu 0.11.3 itself eagerly imports asyncio and stdlib subprocess; it launches no
process for this query. Cold-reader evidence distinguishes that third-party
initialization from forbidden product capture/parser/subprocess dependencies.

Bounds: Kuzu metadata checks stored characters before payload fetch (16 Mi
characters); JSON preflight additionally bounds UTF8 bytes (64 MiB), objects
(100,000) and nesting (64). Source-syntax admission additionally bounds object
nodes (1,000,000), depth (48), string length (16 Mi characters), per-unit facts
(20,000), candidate count (1024) and projection work (1,000,000). Direct objects
are finitely visited and type/enum/bool checked, and native unit identity and
source anchors rechecked. Finite limits do not prove universal latency bounds.
CLI opens read-only with 128 MiB pool/two threads and deterministically closes.
