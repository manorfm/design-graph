# Finite whole-snapshot binding admission

`binding-context/2` is a logical admission revision, not a storage partition or
an execution-cost optimization. Its fixed ceilings are 16 Mi canonical JSON
characters, 64 MiB UTF8 transport bytes, 100,000 JSON objects, JSON depth 64,
64 whole source units, and 4,096 unique qualified roots. All ceilings apply
together; no unlimited or compatibility admission mode exists.

The native producer remains `binding-capture/3`, `binding-ir/3`, and
`static-unit-chain/3`, with its existing 1 MiB whole-unit source and 20-second
native capture limits. Every selected unit and every unit/function-creation
root remains represented. Snapshot readers check source identity, canonical
qualified units, parent/ownership chains, reference origins and nearest
binding resolutions. Increasing these finite transport ceilings does not
weaken those checks or authenticate source provenance.

Before fetching a Kuzu payload, `size(payload)` must fit the character ceiling.
A Unicode scalar occupies at most four UTF8 bytes, so this also bounds the
fetch to 64 MiB. Canonical output is ASCII: the character bound is normally
the tighter byte-cost constraint. The byte check remains explicit on incoming
transport. Depth and object counts are scanned before JSON decoding. An
oversized or malformed database is refused, never truncated or recaptured
implicitly. The database still stores one payload in the existing table.

Completion manifests retain their independent 2 MiB byte/character,
20,000-object and depth-64 parse budget. They do not inherit the larger
snapshot profile. General catalog, primary-key and endpoint identity receipts
remain unchanged.

## Version and rebuild policy

The physical `binding-context-kuzu/1` row schema and `binding-build/3`
completion grammar are unchanged: neither wrapper alone declares logical
compatibility. The completion identity explicitly contains the logical
version, which changes its build fingerprint. A historical manifest cannot
therefore take the unchanged-input reuse path. A reader supporting logical
version 1 refuses version 2, and the current reader refuses version 1; an old
physical wrapper is not permission to reinterpret old facts.

Only a fresh whole-unit native v3 recapture and fully completed normal build
can produce a new accepted derived artifact. Historical v2 capture facts,
source-input/fingerprint caches, diagnostic raw captures, and partial builds
are not upgraded in place. Use a new destination. Any source/profile/adaptor
mismatch, capture failure, admission failure, critical general write failure,
or completion mismatch fails closed without a truthful completion seal. A
failure is not grounds to split units, omit roots, increase operating limits,
or claim the diagnostic capture was a successful build.

## Architecture and retained wire contracts

The pipeline selects an invocation-local whole-unit capture session through
`capture.registry` and its `capture.base` protocol. Format-owned unit selection,
producer asset custody and exact native-to-general coordinate translation stay
inside capture. Graph admission and completion publication stay outside it.

Canonical model key JSON and persisted completion parsing/receipts live in the
model; a cold ownership read never imports build orchestration to validate its
retained completion. Completion limits remain independent of snapshot limits.

`design_graph.source_contract` is a parser-free, immutable wire-profile leaf,
below both capture and the model. It explicitly declares the existing closed
`binding-capture/3` source types (`script`, `module`) and syntax labels (`js`,
`jsx`). It does not select a parser or interpret source. Both native producer
entries and persisted model admission apply the same contract. Model admission
still checks exact field types, semantic structure and budgets independently;
a producer does not confer an admission credential. Stored labels and canonical
envelope bytes are unchanged. Unsupported labels require a separately reviewed
profile change, not an arbitrary string or runtime registry extension.

The source-syntax custody manifest includes this wire contract and the extracted
canonical serializer. Dependency hashes change with reviewed Python source;
vendored native engine bytes and the physical storage format do not change.

## Calibration and scope

Current v3 whole-original diagnostic measurement at parent
`348cf28d78f8038bbf697d6e84e319dba88da218` contained 10 selected units, nine
explicit exclusions, 1,979 unique qualified roots, 56,690 JSON objects, depth
seven and 11,913,342 canonical characters. This is fresh v3 evidence, not the
historical v2 estimate. The selected ceilings leave more than 30% headroom for
both characters and objects. Synthetic whole-source controls exercised 4,096
roots, a wide catch inventory and a 250-block chain, including complete normal
builds, cold reads and reuse under the unchanged 45-second helper and 2 GiB /
zero-swap operating limits. Exact measurements and limitations are recorded
in the implementation evidence, not inferred from constituent timings.

These are implementation calibration results, not independent review,
production, installed-wheel, MCP/assembly or promotion approval. The prior
cost optimization and this admission revision require separate review.
