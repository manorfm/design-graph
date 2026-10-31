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
   inputs (concrete example paths below; provision your own absolute paths and
   use the fingerprint of that exact reviewed toolchain):

   ```sh
   design-graph /home/alice/prototypes/prototype.html --db /home/alice/graphs/new.db --json \
     --binding-node /home/alice/toolchains/node-26.7.0-linux-x64/bin/node \
     --binding-engine /home/alice/toolchains/prepared-engine \
     --binding-fingerprint d7ad68c53405476f21a1e2d93851ce9c29bdd51d9fb3b1f74b58756fb1541691
   ```

3. Read `/home/alice/graphs/new.db.binding.json`. Use its exact `snapshot` and an
   explicit `roots` entry's `unit` and `region`; never infer those from an assembly
   name. A manifest is a selector inventory, not independent authentication.
4. Launch the installed **public `design-mcp` console script**, with a per-process
   absolute `GRAPH_DIR` pointing at a dedicated empty directory and metrics
   disabled. This is the verified binding-only route, not a private
   `MCPServer([])` launcher. The directory must **stay empty throughout the
   session**: the existing server checks for graph-directory changes before
   each dispatch and can reload legacy readers. The explicitly selected target
   database may be outside `GRAPH_DIR` (as in the example below).

   This concrete retained-review example uses the installed executable and tiny
   database from the bounded console-entrypoint acceptance review; these local
   evidence paths are not installation defaults. On another machine, provision
   equivalent absolute paths rather than copying unavailable evidence paths.

   ```sh
   review=/home/manoelmedeiros/.hermes/cache/scratch/design-graph-architecture-reset-20261030
   mkdir -p "$review/consumer-console-docs/empty-graphs"
   GRAPH_DIR="$review/consumer-console-docs/empty-graphs" \
   DESIGN_GRAPH_METRICS_DISABLED=1 \
   "$review/consumer-integration-final/installed-venv/bin/design-mcp"
   ```

   Do not put any databases in that dedicated directory or share it with a
   builder. Passing `db` in a later tool call alone does **not** prevent preloads.
   With a populated `GRAPH_DIR`, normal startup still eagerly opens unrelated
   legacy `*.db` files without the companion's buffer/thread bounds. Neither
   that legacy startup nor arbitrary normal startup is certified graph-only or
   bounded by this companion. No global config change or activation is involved.
5. Use SDK stdio with that executable as `command`, no Python harness arguments,
   then `initialize`, `tools/list`, and qualified `tools/call`. This runnable
   example reads selectors from the retained tiny database's manifest rather
   than using guessed identifiers. Run it with the installed venv's Python
   (which has the MCP SDK), saving it as a local script if needed:

   ```python
   import asyncio
   import json
   import os
   from pathlib import Path

   from mcp import ClientSession, StdioServerParameters
   from mcp.client.stdio import stdio_client

   review = Path("/home/manoelmedeiros/.hermes/cache/scratch/design-graph-architecture-reset-20261030")
   graph_dir = review / "consumer-console-docs/empty-graphs"
   graph_dir.mkdir(parents=True, exist_ok=True)
   assert not any(graph_dir.iterdir()), "GRAPH_DIR must stay empty"
   db = review / "consumer-integration-independent/installed-new.db"
   manifest = json.loads(Path(str(db) + ".binding.json").read_text())
   root = manifest["roots"][0]  # Explicit qualified root, not an assembly name.
   params = StdioServerParameters(
       command=str(review / "consumer-integration-final/installed-venv/bin/design-mcp"),
       args=[],
       env={**os.environ, "GRAPH_DIR": str(graph_dir),
            "DESIGN_GRAPH_METRICS_DISABLED": "1"},
   )

   async def main():
       async with stdio_client(params) as streams:
           async with ClientSession(*streams) as client:
               await client.initialize()
               tools = (await client.list_tools()).tools
               assert any(tool.name == "get_binding_context" for tool in tools)
               result = await client.call_tool("get_binding_context", {
                   "db": str(db), "snapshot": manifest["snapshot"],
                   "unit": root["unit"], "region": root["region"],
               })
               assert not result.is_error, result
               print(result.content[0].text)

   asyncio.run(asyncio.wait_for(main(), timeout=20))
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

This is a **trusted-local capability under the server account's OS permissions**.
The absolute database path is not confined to `GRAPH_DIR`, symlinks are not
forbidden, and read-only access is not a multi-tenant filesystem boundary. Use
least-privilege OS permissions; do not expose this stdio service as an
unrestricted remote filesystem service. Selector limits do not certify hostile
protocol framing or arbitrary native database files as safe.

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
