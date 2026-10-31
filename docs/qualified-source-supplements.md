# Qualified stored-source supplements

`get_full(aspect="source")` and `assemble_page` accept optional `db`, `snapshot`,
`source_selections`, and `expected_sha256`. Supply all of `db`, `snapshot`, and
`source_selections` together; partial or mixed `doc`/qualified requests fail closed.
The explicit existing absolute database is opened read-only with a 128 MiB Kuzu
pool and two threads. The persisted snapshot is fully admitted by the existing
binding-context checker before any source is selected. No new capture, source
store, schema, owner linker or runtime engine is involved.

Example argument shape (replace placeholders with retained build identities):

```json
{
  "name": "helper",
  "aspect": "source",
  "db": "/absolute/path/prototype.db",
  "snapshot": "<64 lowercase hexadecimal characters>",
  "source_selections": [{
    "unit": "u:<checked unit identity>",
    "region": "r17",
    "mode": "region"
  }]
}
```

`region` mode (the default) returns exactly the checked region. An optional
`interval: [start, end]` must equal that region's UTF-8 byte bounds. No function
body is inferred from a declaration occurrence, owner name, label, binding or
member access. `get_full`'s `name` is not used to resolve qualified selections;
only the explicit unit/region selects bytes. There is no ambiguous-name or
first-name fallback.

For retained statements or initializer syntax without an exact dedicated IR
region, use `mode: "retained-interval"`, select the exact **unit root region**,
and supply both `interval` and an inline receipt:

```json
{
  "unit": "u:<checked unit identity>",
  "region": "r0",
  "mode": "retained-interval",
  "interval": [2085, 2132],
  "receipt": {
    "unit_sha256": "<independently retained original whole-unit SHA-256>",
    "interval": [2085, 2132],
    "source_sha256": "<independently retained original selected-byte SHA-256>"
  }
}
```

This explicitly selects retained bytes, not an automatically proved declaration
or dependency. Receipts are inline hashes/intervals, never paths to read. Their
trust comes from independent retention by the caller, not this mutable database.
A receipt checks ordinary byte fidelity, **not source-to-IR authentication**.
An optional `expected_sha256` checks an independently retained snapshot digest.
Coherent rewrites without a retained external anchor cannot be authenticated.

All evidence is IR_ONLY. Initialization and current/runtime values remain
**unknown**. Original initializer text is syntax only. K/window.V6K alias/member
values, execution order, cross-unit linkage, complete dependency closure, and
legacy graph-to-binding snapshot correspondence are not certified.

For qualified assembly use an exact stored screen name instead of `aspect`.
Legacy content and selected supplements come from the same explicit DB, without
session/doc reader mixing. Supplements are labelled separately and included in
the actual deterministic part count. Repeat identical arguments with `part=N`;
`known` only suppresses legacy component definitions, never explicit supplements.
Up to 16 nonduplicate selections and 512 KiB of aggregate selected UTF-8 source
are accepted. Invalid parts, selectors, receipts, budgets and snapshots fail
closed. No silent truncation or first-name fallback is used.

Without qualified arguments, successful legacy source/data and assembly content
are preserved byte-for-byte. Only a structured legacy source miss activates a
bounded lexical fallback on the already selected doc/session reader connection.
It discovers at most two snapshot identities and admits a singleton once, but
**admission and singleton cardinality are not ownership**. Before name selection
or automatic source emission, the ownership gate refuses with explicit
`Source ownership/correspondence unknown` when the selected legacy graph cannot
associate its complete document/build source inventory to that exact snapshot.

The current legacy model has no such persisted association: Model records only
version/capture; source rows have no build, snapshot or unit identity. State is
build-diff metadata. The completion manifest's general receipt commits graph
keys/edges rather than source payloads. A whole unique component matching a
qualified region proves a shared fragment, not ownership of the other units or
helpers; it cannot exclude stale same-shape builds or mixed communities. Names,
paths, working directory, same connection and disclaimers do not repair this.
Consequently **automatic fallback is currently withheld even for the retained
original**; its actual source ownership is unknown, not disproved. Successful
legacy retrieval and explicit qualified source retrieval remain available.

The source-context selection/formatting controls below remain isolated controls,
not an ownership positive or an enabled automatic delivery claim.
The isolated source-context selector follows checked same-unit lexical reference targets. It formats
function-region bytes and declaration-identifier line excerpts with UTF-8 byte
bounds and hashes. A line excerpt is source context, **not a complete initializer
or runtime value**: full declaration extent and multiline continuation stay
unknown. It never guesses initializer ends or dumps the entire source unit.
The existing structured source paginator preserves opaque source bytes. Repeat
identical doc/session/name/aspect arguments with `part=N`; `known` does not hide
this evidence. Limits: 512 KiB aggregate source, 64 context records, 4096 captured
references in the selected unit, plus the existing whole-snapshot admission limits.
There is no cross-invocation checked-object cache.

This direct helper-source correction does not implement automatic assembly
linkage. In particular, the original screen chain still lacks the association
`K = window.V6K` needed to reach the helper. R13 assembly closure remains open;
source context does not certify runtime values, source-to-IR authenticity or
legacy graph-to-binding snapshot correspondence.
