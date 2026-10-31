# Qualified binding context companion

`get_binding_context` is a registered read-only MCP tool. It is a **separate
companion**, not an upgraded certificate for `assemble_page`, `get_full`, a screen,
or an owner body. The caller must supply an absolute existing Kuzu database file,
`snapshot`, `unit` and `region`. There is no document/name lookup, first-match
mapping, source-body return, or implicit build.

## Supported workflow

1. Provision the exact reviewed engine offline as described in
   `src/design_graph/capture/binding_engine/README.md`. Installing the Python wheel
   includes the adapter/patch/pin/lock/license assets, **not** the external Node
   executable or npm dependency tree. The capture provider has no default engine,
   performs no install/discovery and verifies explicitly supplied pinned bytes.
2. Build a **new** destination with the normal CLI, explicitly selecting all three
   inputs (absolute paths; substitute real deployment paths):

   ```sh
   design-graph /absolute/prototype.html --db /absolute/new.db --json \
     --binding-node /absolute/pinned/node \
     --binding-engine /absolute/prepared-engine \
     --binding-fingerprint d7ad68c53405476f21a1e2d93851ce9c29bdd51d9fb3b1f74b58756fb1541691
   ```

3. Read `/absolute/new.db.binding.json`. Use its exact `snapshot` and an explicit
   `roots` entry's `unit` and `region`; never infer those from an assembly name.
   A manifest is a selector inventory, not independent authentication.
4. Normal `design-mcp` advertises the tool alongside existing tools. For a
   **binding-only** stdio session that does not preload legacy GraphReaders or
   discover prototype directories, configure the installed Python executable
   with these arguments (the `-c` value is one argument):

   ```sh
   /absolute/venv/bin/python -c 'import asyncio; from design_graph.interface.mcp.server import MCPServer, run_stdio; asyncio.run(run_stdio(MCPServer([])))'
   ```

   No global configuration change is required. Normal `design-mcp` startup still
   has its existing legacy reader-loading behavior; this companion does not
   claim to make that unrelated startup path graph-only or bounded.
5. Send `tools/call` with name `get_binding_context` and arguments:

   ```json
   {"db":"/absolute/new.db","snapshot":"<exact manifest snapshot>","unit":"<exact root unit>","region":"<exact root region>"}
   ```

   Optionally supply `expected_sha256` (64 lowercase hexadecimal characters)
   retained through an **independently trusted** capture custody channel. A digest
   read from that same database or manifest is not independent authentication.
   The returned text is the same sorted-key JSON as normal
   `design-query binding-context --db ... --snapshot ... --unit ... --region ...`
   (CLI adds a trailing newline).

Each call opens Kuzu read-only with 128 MiB buffer pool / two threads, re-admits
stored state through the public reader, and closes connection then database even
on query failure. Missing files are refused without initialization. Malformed
arguments, absent dependencies, unknown qualified roots, digest mismatch and
catalog/admission failures are MCP tool errors (`isError`), not successful proof
text. A missing extension remains `legacy/unknown`, exactly as the public CLI;
it is never synthesized into qualified evidence. Selectors are bounded to 4096
characters each; unknown keys and name/doc aliases are refused.

Available context is `IR_ONLY`; initialization and value remain `unknown`.
Stored provenance consistency does not authenticate arbitrary coherent rewrites
or source-to-IR derivation. This path does not parse source, launch Node or
establish runtime linkage between units. Obtain any legacy assembly separately;
retain its uncertified status. There is intentionally no mechanism to merge a
name-only assembly body into qualified proof.

## Installation and default policy

Binding capture remains **opt-in** in the normal build. It is not default-on.
Explicit absolute engine selection and fingerprint verification remain required;
no ambient discovery, network parser installation or global/default configuration
was introduced. Supported JS/JSX static-unit profiles and explicit rejection/gap
boundaries remain those documented by the engine README. This integration does
not finish unrestricted language coverage, cross-unit imports, runtime values,
legacy owner mapping, original-database replacement or production deployment.

If deployment requires a default workflow later, a concrete safe hook is a
versioned **explicit launcher**, e.g. `design-graph-pinned-v1`, provisioned by an
operator with immutable absolute Node/toolchain paths and the exact pin. It would
pass those three values to `BindingBuildOptions` on each invocation and fail
closed when unavailable or changed. It must not search PATH/npm/home, fall back
to unqualified capture, or override user-supplied conflicting pins. That hook
requires separate review and activation; it is a proposal, not installed or
enabled here.
