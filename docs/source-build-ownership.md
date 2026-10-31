# Fresh BUILD source ownership v1

`binding-build/4` creates a typed `source-build-ownership/1` append-only logical
receipt in the unchanged `BindingContextSnapshot` physical JSON table. Existing
`binding-general-completion/1` shape receipts retain their original meaning.

The local builder commits every property and the schema of all 39 general tables,
relationship endpoints, keys, nulls, Model identity and multiplicity. Each STRING
property has a `(table, key/endpoints, field, payload SHA-256)` owner locator. The
receipt's common document/Screen domain, whole-input SHA-256, input locator,
complete ordered script-unit inventory and coverage exclusions qualify those
locators. Every admitted unit carries source bytes/hash/options, lexical facts,
syntax facts and pinned engine/adaptor identities. HTML source is not invented as
a JavaScript unit: ownership is of the **document-build inventory** only. Precise
JS unit/region selection for individual HTML/component fields remains unknown
and requires a separately reviewed adapter.

Normal builds reuse the pinned syntax producer, deriving lexical output from that
same capture. General, lexical, qualified-syntax and ownership writes use separate
non-nested transactions in a private database. After deterministic close, the
builder reopens and checks the private database before an atomic no-clobber link
to a new destination. It then publishes state without clobbering an existing
sidecar, and finally links an independently retained `.binding.json` completion
seal with the receipt's version, logical key and payload digest. These filesystem
steps are **not** a multi-file atomic transaction. A failure after DB publication
can leave an orphan; without the final seal it cannot load as ownership-positive.
No existing database is deleted before promotion. Failed private artifacts may
remain for diagnosis and are not discoverable ownership-positive builds.

`load_source_build_ownership(reader)` derives its domain from a normal reader's
selected database/state path and current Screen inventory. It does not accept a
caller provenance flag, snapshot selector or digest. It requires the retained
completion, rechecks its fingerprint, independently anchored payload, complete
syntax/lexical inventory, current schemas, Model and full properties in one
read-only transaction. Reuse performs these checks before reporting `skipped`.
Qualified syntax CLI reads remain separately qualified and still report general
source-payload ownership unknown. No MCP or R1 guard was enabled or changed.

This is a **trusted local builder** consistency/custody contract, not a signature
or cryptographic authentication. Someone able to coherently rewrite the entire
graph, all envelopes and independently retained completion can forge consistency;
a digest taken solely from the mutable database is not an independent anchor.
There are no runtime-value, script-order or execution claims.

Bounds: 64 MiB exact UTF-8 document, 16 whole syntax units, 4096 coverage records
and selected Screens, existing syntax/physical hostile JSON caps, 100000 general
rows/owner locators, 8 MiB total canonical general-property bytes. String aggregate
sizes are checked before fetching payloads. The completion retains its separate
2 MiB/20000-container/64-depth cap. Builds run with the existing 20-second native
capture timeout. Tests/evidence use real shared flock, 2 GiB memory, zero swap,
120-second batches, 45-second CLI calls and 128 MiB/two-thread Kuzu.

Kuzu initialization transitively imports asyncio/subprocess. Cold installed-reader
evidence records that dependency exception, then removes the subprocess cache and
blocks product capture/parser/pipeline imports and all process execution. It does
not bypass the qualified reader's admission checks.

Independent review is required before consumer assembly, automatic delivery or
any full-corpus/original-database replacement.
