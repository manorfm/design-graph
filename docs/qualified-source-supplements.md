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

Without qualified arguments, legacy useful source/data and assembly content are
preserved. Normal dispatch replaces unsupported completeness/absence assertions
with explicit coverage limits. Legacy name lookup may still lack a helper body;
that is different from direct qualified source being available. Automatic
name/member-to-source resolution remains unsupported.
