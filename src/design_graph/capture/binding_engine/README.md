# Explicit corrected binding engine (capture milestone)

The runtime provider is `design_graph.capture.binding_capture.BindingCapture`.
It has **no default toolchain** and never installs dependencies. Supply absolute
`node` and `toolchain` paths and the exact fingerprint below:

```
d7ad68c53405476f21a1e2d93851ce9c29bdd51d9fb3b1f74b58756fb1541691
```

This fingerprint is SHA256 of canonical compact, sorted-key `pin.json` (without
the newline). It covers the pinned Node **version** v26.7.0 and the SHA256 of
1,454 external artifact files: native parser dependencies, the corrected scope
manager, API, patch and lock. The provider rechecks these bytes on every capture.
The executable and directories must be provisioned by the caller as immutable,
trusted local inputs; this is not a sandbox against concurrent malicious writes
or a signed parser-attestation mechanism.

- Parser and upstream scope manager: `@typescript-eslint/*` **8.72.1**.
- Scope patch: **design-graph-fdi-2**, exact `engine-final.patch`.
- TypeScript parser dependency: **6.0.3**, exact lock metadata.
- The original locked research dependency inventory is retained byte-for-byte
  for reproducibility, including unused comparison packages. The product imports
  **only** the corrected TypeScript-ESLint engine, never comparison resolvers.
- Upstream scope-manager and typescript-estree MIT notices are included. External
  npm packages retain their own original license files; do not strip them.

## Build/provisioning (offline, explicit)

Provision the dependencies from this exact `package-lock.json` in a dedicated
build environment. A deployment may use `npm ci --ignore-scripts` explicitly in
that directory; **the capture provider never runs npm**. The build recipe itself
needs Python 3.12+ and Git and performs no download/install:

```sh
python /absolute/path/to/binding_engine/prepare.py \
  --dependencies /absolute/path/to/provisioned/node_modules \
  --output /absolute/path/to/new-toolchain
```

The output path must not exist. The recipe verifies locked dependencies, copies
only the upstream scope-manager package, applies the maintained patch, retains
MIT licenses and verifies **every resulting pinned byte**. Dependencies are
linked explicitly, not copied into the repository. Failed builds are never
accepted by the provider; their output directory is left for diagnosis.
The recipe was exercised against the real installed upstream artifacts, and its
result was consumed by the real capture provider and Python checker.

## Product API

```python
from pathlib import Path
from design_graph.capture.binding_capture import BindingCapture

producer = BindingCapture(
    node=Path('/explicit/pinned/node'),
    toolchain=Path('/explicit/corrected/toolchain'),
    fingerprint='d7ad68c53405476f21a1e2d93851ce9c29bdd51d9fb3b1f74b58756fb1541691',
)
capture = producer.capture(
    b'const X=1;function f(p=()=>X){function X(){}var X;return X;}',
    locator='unit.js', source_type='module', syntax='js',
)
result = capture.check()  # real independent Python first-binding lookup
serialized = capture.to_json()
```

Inputs are entire explicit UTF8 JS/JSX units, at most 1 MiB. `source_type` is
`script` or `module`; `syntax` is `js` or `jsx`. A JS request containing TS syntax
is refused, not silently analyzed as JS. Calls time out after 20 seconds.
UTF16 engine offsets are converted with one linear boundary map into canonical
UTF8 byte spans, preserving escapes, astral characters, BOMs and CRLF bytes.
Every native declaration definition is exported, not just `defs[0]`. Canonical
binding identity is distinct from declaration occurrence identity. Ordinary
functions' source-less `arguments` cells are explicit intrinsic records with
**zero fake declarations**. Named function-expression and class name bindings
retain their real identifier occurrences, including separate inner/outer class
binding identities where the same identifier token creates two bindings.

## Versioned profile and limits

`binding-capture/2` wraps `binding-ir/2`, profile `static-unit-chain/2`.
The v1 profile and its 69 controls remain valid and separate. The extension adds:

- whole static script/module-unit declarations (not a normative Global Record);
- class/name typed creation regions and declaration kinds;
- source-less ordinary-function `arguments` intrinsic bindings, with explicit
  ordinary/arrow function-site metadata;
- localized coverage reasons for `with`, sloppy direct eval and Annex B.

The producer adapts the native scope manager's **targets**, never resolves names
itself. AST-derived typed evaluation regions supply parameter-default closure,
function-body lexical and switch discriminant/case origins. Python independently
checks first-binding lookup and native target/chain consistency. A native scope
is not asserted to equal a normative ECMAScript Environment Record. Native
root/global/module scopes are projected onto one explicitly **static-unit** root;
function body lexical cells are separated from function var cells.

Lexical `for`, `for-in` and `for-of` headers own a static block environment;
`var` and assignment headers inherit their enclosing environment. Explicit AST
phase sites cover initialization/left binding, test, update, RHS and body. The
lexical RHS sees the loop name even where runtime access would encounter TDZ.
Nested closures retain this static chain. These are abstract source bindings:
per-iteration cell identities, initialization, iterator execution and values
remain unknown. No concrete iteration environment or runtime execution is claimed.

Known contracted positives include lexical shadowing, parameter expressions,
function+var in both orders, var+var, implicit arguments/arguments shadowing,
named function expressions, class/extends/method controls and JSX references.
Function/block declarations are interpreted lexically where applicable. Duplicate
source declarations remain distinct occurrences of the one canonical binding.

Dynamic `with` bodies, affected sloppy-eval functions/units and Annex-B-affected
functions/units yield explicit **unknown**, without poisoning unrelated sibling
functions. TS/TSX is outside this capture contract. Imports, catch-specific
scopes, class field/static-block environments and other unmapped native scopes
are currently fail-closed, not silently approximated. Such boundaries may reject
the whole unit; accepted dynamic gaps are localized. Unbound globals are
**unresolved**, never proved, and host/global-object properties and cross-unit
imports are not modeled. Strictness and ECMAScript early errors are delegated to
the native parser/engine; this is not a complete conformance validator.

`check()` produces **IR_ONLY** evidence. Lexical target, initialization, value,
provenance and admission evidence remain separate; initialization/value are
**unknown**, including TDZ case-header references. No receipt, persisted/public
artifact, rebuild or end-to-end product acceptance is claimed by this milestone.
