# design-graph

Parse a standalone HTML prototype into a knowledge graph and expose it through MCP — giving LLM agents surgical access to screens, components, design tokens, and interactions at a fraction of the token cost.

> **The problem:** Passing raw prototype HTML to an LLM costs 50–200k tokens per request and forces the model to infer structure from noise. `design-graph` pre-indexes that structure so agents query exactly what they need — typically 200–400 tokens per call.

---

## Requirements

- Python 3.9 or later
- `pip` (comes with Python)
- Cursor, Claude Code, or any MCP-compatible client

---

## Install

```bash
pip install git+https://github.com/manorfm/design-graph.git
```

This installs three commands globally: `design-graph`, `design-mcp`, and `design-query`.  
Dependencies (`beautifulsoup4`, `kuzu`) are installed automatically.

To verify:

```bash
design-graph --help
```

---

## Step 1 — Build the graph

Navigate to the folder where your prototype HTML lives and run:

```bash
design-graph myapp.html
```

That's it. The graph is saved automatically to:

```
~/.local/share/design-graph/myapp.db
```

You can build multiple prototypes — each gets its own `.db` file named after the HTML:

```bash
design-graph app-v1.html    # → ~/.local/share/design-graph/app-v1.db
design-graph admin.html     # → ~/.local/share/design-graph/admin.db
```

**Options:**

| Flag | Description |
|---|---|
| `--db <path>` | Save to a custom location instead of the default directory |
| `--diff` | Show what changed since the last build |
| `--force` | Force a full rebuild even if the HTML hasn't changed |

If you run the same command again on an unchanged file, the build is skipped (MD5 hash check). Use `--force` to override.

---

## Step 2 — Configure the MCP server

Add the following to your MCP config file. No paths, no env vars — the server finds the graphs automatically.

**Cursor** → `~/.cursor/mcp.json`

**Claude Code** → `~/.claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "design-graph": {
      "command": "design-mcp"
    }
  }
}
```

Restart Cursor / Claude Code after saving the config.

### What happens on startup

The server scans `~/.local/share/design-graph/` for `.db` files and loads them all. During the MCP handshake it announces the available prototype names:

```
[design-graph] Started — 2 prototype(s): app-v1, admin
```

If no graphs are found yet, the server starts in **degraded mode** — it keeps running so the MCP connection stays alive, and every tool call returns a setup instruction:

```
No graphs loaded. Build one first:
  design-graph <prototype.html>
Looking in: /Users/you/.local/share/design-graph
```

### Custom graph directory

If you want to store graphs somewhere else (e.g. a shared folder), set `GRAPH_DIR`:

```json
{
  "mcpServers": {
    "design-graph": {
      "command": "design-mcp",
      "env": { "GRAPH_DIR": "/path/to/your/graphs" }
    }
  }
}
```

---

## Step 3 — Query from your editor

Once the MCP server is running, your agent can call the tools directly. You can also query from the terminal without any editor:

```bash
design-query screens                    # list all screens across all prototypes
design-query tokens color               # list color design tokens
design-query search "button"            # search components, screens, tokens, texts
design-query inspect SectionCard        # full component details
design-query impact SectionCard         # what breaks if this component changes
design-query screen RestaurantsPage     # full screen composition
```

---

## MCP tools reference

| Tool | What it returns | Key params |
|---|---|---|
| `list_screens` | All screens grouped by prototype | — |
| `get_screen` | Sections, components, texts and styles of a screen | `name`, `doc` |
| `get_section` | Details of a named visual section inside a screen | `screen`, `section`, `doc` |
| `get_component` | JSX snippet, styles, tokens, interactions, texts | `name`, `doc` |
| `get_tokens` | Color and spacing design tokens | `category?`, `doc` |
| `find_token_usage` | Where a given token value is used | `value`, `doc` |
| `search` | Cross-entity search (supports PT/EN aliases) | `query` |
| `impact` | Screens and sections affected by changing a component or token | `name`, `doc` |
| `get_full_jsx` | Full unsanitized JSX for a component | `name`, `doc` |
| `get_component_interactions` | Hover/focus states with CSS transitions | `name`, `doc` |

### The `doc` parameter

When more than one prototype is loaded, pass `doc` to every tool call. Its value is the `.db` filename without extension — the same name printed at startup.

```
# Two prototypes loaded: app-v1, admin
get_component(name='SectionCard', doc='app-v1')   ✓ correct prototype
get_component(name='SectionCard')                  ⚠ defaults to first loaded
```

The server returns a clear error if the value doesn't match any loaded prototype:

```
Prototype 'foo' not found.
Available: 'app-v1', 'admin'
Use list_screens to see all loaded prototypes.
```

---

## Multiple prototypes

```bash
# Build both
design-graph app-v1.html
design-graph admin.html

# Server loads both automatically — no config change needed
# Use doc= to target the right one
```

Both graphs live in `~/.local/share/design-graph/`. The server finds them on startup without any additional configuration.

---

## Makefile shortcuts

If you cloned the repo and prefer `make`:

```bash
make build   PROTO=myapp.html     # build / update graph
make rebuild PROTO=myapp.html     # force full rebuild
make diff    PROTO=myapp.html     # show what changed since last build

make start                        # start MCP server in background
make stop                         # stop MCP server
make restart                      # restart MCP server
make status                       # check if running
make logs                         # tail server logs

make screens                      # list all screens
make tokens                       # list color tokens
make search  Q='button'           # search the graph
make inspect C='SectionCard'      # component details
make impact  C='SectionCard'      # impact analysis
make screen  S='RestaurantsPage'  # screen composition
```

---

## Why graphs are efficient for agents

### Surgical context, not flooding

| Approach | Tokens | What the LLM gets |
|---|---|---|
| Raw HTML | 50–200k | Infers structure from noise |
| Vector search chunks | ~2k | May be wrong context |
| `get_component('SectionCard')` | ~300 | Exact JSX + styles + tokens |

### Graph traversal replaces inference

Each tool runs a Cypher query that crosses multiple relationships in one call:

```
impact('SectionCard')
→ Component → Screen, Component → Section, Component → Token
→ 4 affected screens, 2 dependent tokens — in a single round-trip
```

### Typed data, no guessing

`get_tokens(category='color')` returns `primary = #ffb81c (47 uses)`. The agent doesn't infer the primary color from scattered CSS — it reads a fact.

Every CSS property is stored in `Style` with an explicit state (`default | hover | transition`), not buried in JSX.

### Fuzzy match + PT/EN aliases

`search('botão')` expands to `['btn', 'button', 'Button']` automatically.  
`get_component('Button')` resolves to `BtnPrimary` without an extra call.

### Incremental builds

The builder hashes the HTML before processing. Unchanged files are skipped. A full rebuild of a large prototype takes ~5 seconds.

### Sanitized JSX

Event handlers, arrow functions with bodies, and large ternary expressions are stripped. The agent receives visual structure in ~20 lines instead of 400.

---

## Graph schema

![Schema](./schema.svg)

> Editable source: [`diagram.excalidraw`](./diagram.excalidraw)

### Nodes

| Node | Properties |
|---|---|
| `Screen` | name (PK), component_count, sections_count |
| `Section` | id (PK), screen, name, styles_json, components_json, texts_json, jsx_snippet |
| `Component` | name (PK), comp_type, jsx_snippet, occurrence, classes |
| `Token` | id (PK), category (color\|spacing), label, value, usage |
| `Style` | id (PK), element, state (default\|hover\|transition), property, value |
| `Interaction` | id (PK), trigger (hover\|focus), css_prop, from_val, to_val, transition |
| `UIText` | id (PK), content, text_type (heading\|label\|button\|placeholder), source, element |

### Edges

```
Screen    ──USES_COMPONENT──►  Component
Screen    ──HAS_SECTION──────►  Section
Screen    ──SCREEN_HAS_TEXT──►  UIText
Section   ──SECTION_USES─────►  Component
Component ──HAS_STYLE────────►  Style
Component ──USES_TOKEN───────►  Token
Component ──COMP_HAS_TEXT────►  UIText
Component ──HAS_INTERACTION──►  Interaction
```

---

## File structure

```
.
├── build_graph.py             # HTML → Kuzu graph builder  (CLI: design-graph)
├── mcp_server.py              # MCP server                 (CLI: design-mcp)
├── query.py                   # Terminal query interface   (CLI: design-query)
├── _paths.py                  # Shared path resolution (env → config → XDG)
├── extract_design_system.py   # Alternative: markdown extraction
├── watch_prototype.sh         # fswatch wrapper for live reload
├── Makefile                   # Convenience shortcuts (clone-based workflow)
├── pyproject.toml             # Package config + CLI entry points
├── mcp-config.example.json    # Minimal MCP config template
├── schema.svg                 # Graph schema diagram
└── diagram.excalidraw         # Editable diagram source

~/.local/share/design-graph/   # Default graph storage (created automatically)
  ├── myapp.db                 # One .db per prototype
  └── admin.db
```

---

## License

MIT
