# design-graph

Parse a standalone HTML prototype into a knowledge graph and expose it through MCP — giving LLM agents surgical access to screens, components, design tokens, and interactions at a fraction of the token cost.

> **The problem:** Passing raw prototype HTML to an LLM costs 50–200k tokens per request and forces the model to infer structure from noise. `design-graph` pre-indexes that structure so agents query exactly what they need — typically 200–400 tokens per call.

---

## How it works

```
prototype.html → design-graph build → myapp.db → design-mcp → Cursor / Claude Code
```

1. **`design-graph build`** parses the compiled JavaScript inside the HTML, extracts React components, screens, inline styles, color/spacing tokens, hover interactions, and UI text strings — then stores everything as typed nodes and edges in a [Kuzu](https://kuzudb.com/) embedded graph database.
2. **`design-mcp`** starts an MCP server (JSON-RPC 2.0 over stdio) that exposes 10 focused query tools. The LLM client calls these instead of reading raw HTML.
3. **Multiple prototypes** are supported: set `GRAPH_DIR` to a folder and all `.db` files inside are loaded automatically. Pass `doc='project-name'` to scope any tool call to the right prototype.

---

## Install

```bash
pip install git+https://github.com/YOUR_USERNAME/design-graph.git
```

For local development:

```bash
git clone https://github.com/YOUR_USERNAME/design-graph.git
cd design-graph
pip install -e .
```

**Requirements:** Python 3.9+ — `beautifulsoup4` and `kuzu` are installed automatically.

---

## Quick start

```bash
# 1. Build the graph from your prototype
design-graph myapp.html

# 2. Query directly from the terminal (no Cursor needed)
design-query screens
design-query inspect SectionCard
design-query search "button"

# 3. Wire up the MCP server — see mcp-config.example.json
```

---

## CLI reference

### `design-graph` — build the knowledge graph

```
design-graph <prototype.html> [options]

Options:
  --db <path>     Output .db path  (default: ~/graphs/<basename>.db)
  --diff          Show what changed since the last build
  --force         Force a full rebuild even if the HTML is unchanged
```

### `design-mcp` — start the MCP server

```
GRAPH_DIR=~/graphs design-mcp
```

Normally started automatically by Cursor/Claude when registered as an MCP server. Loads all `.db` files from `GRAPH_DIR` and announces the available prototype names during the MCP handshake.

### `design-query` — query without an MCP client

```
design-query screens
design-query tokens [color|spacing]
design-query search <term>
design-query inspect <ComponentName>
design-query impact <ComponentName>
design-query screen <ScreenName>
```

---

## Makefile shortcuts

```bash
make build   PROTO=myapp.html     # build / update graph
make rebuild PROTO=myapp.html     # force full rebuild
make diff    PROTO=myapp.html     # show what changed

make start                        # start MCP server in background
make stop / restart / status / logs

make screens                      # list all screens
make search  Q='button'           # search the graph
make inspect C='SectionCard'      # component details
make impact  C='SectionCard'      # impact analysis
make screen  S='RestaurantsPage'  # screen composition
```

---

## MCP setup

Copy `mcp-config.example.json` to `~/.cursor/mcp.json` (Cursor) or your Claude Code config and update the path:

```json
{
  "mcpServers": {
    "design-graph": {
      "command": "design-mcp",
      "env": {
        "GRAPH_DIR": "/path/to/your/graphs"
      }
    }
  }
}
```

If you haven't installed via pip, use the Python fallback:

```json
{
  "mcpServers": {
    "design-graph": {
      "command": "python3",
      "args": ["/path/to/design-graph/mcp_server.py"],
      "env": {
        "GRAPH_DIR": "/path/to/your/graphs"
      }
    }
  }
}
```

---

## MCP tools

| Tool | What it returns | Params |
|---|---|---|
| `list_screens` | All screens across all loaded prototypes | — |
| `get_screen` | Full composition: sections, components, texts, styles | `name`, `doc` |
| `get_section` | Details of a named visual section | `screen`, `section`, `doc` |
| `get_component` | JSX snippet, styles, tokens, interactions, texts | `name`, `doc` |
| `get_tokens` | Color and spacing design tokens | `category?`, `doc` |
| `find_token_usage` | Where a given token value is used | `value`, `doc` |
| `search` | Cross-entity search (supports PT/EN term aliases) | `query` |
| `impact` | Screens and sections affected by changing a component/token | `name`, `doc` |
| `get_full_jsx` | Full unsanitized JSX for a component | `name`, `doc` |
| `get_component_interactions` | Hover/focus states with CSS transitions | `name`, `doc` |

### The `doc` parameter

Required whenever more than one prototype is loaded. Its value is the `.db` filename without extension (e.g. `doc='myapp'`). The server announces available names during `initialize` — use `list_screens` to confirm them at any time.

Without `doc`, the server falls back to the **first loaded database** and silently returns data from the wrong project. Always pass it when working with multiple prototypes.

---

## Why graphs are efficient for agents

### Surgical context vs. flooding

Traditional tooling passes full files to the LLM. The graph inverts that: the agent asks a precise question and receives exactly what it needs — nothing more.

| Approach | Tokens consumed | What the LLM gets |
|---|---|---|
| Pass the raw HTML | 50–200k | Infers structure from noise |
| Vector search over chunks | ~2k | Fragment may be wrong context |
| `get_component('SectionCard')` | ~300 | Exact JSX + styles + tokens |

### Graph traversal replaces inference

Each tool runs an optimized Cypher query with multiple hops. The agent doesn't need to chain calls — one request already crosses relationships:

```
impact('SectionCard')
→ 1 query, 3 hops: Component → Screen, Component → Section, Component → Token
→ result: 4 affected screens, 2 dependent tokens
```

### Typed data eliminates guessing

The agent doesn't need to infer "which hex is the primary color?" — `get_tokens(category='color')` returns `primary = #ffb81c (47 uses)`. Every CSS property is stored in `Style` with an explicit state (`default | hover | transition`), not scattered across JSX.

### `doc` as a context isolator

Multiple prototypes loaded, zero cross-contamination. Without `doc`, a query silently hits the wrong database. With `doc='myapp'`, every Cypher query is scoped to that graph. The guarantee is structural — not a convention the agent has to remember.

### PT/EN aliases reduce naming mismatches

`search('botão')` expands automatically to `['btn', 'button', 'Button']`. The agent doesn't need to know the prototype's naming convention to find the right component.

### Fuzzy match handles approximate names

`get_component('Button')` → `[MCP] fuzzy: 'Button' → 'BtnPrimary'`. No extra round-trip. Resolution order: prefix → suffix → substring.

### Incremental builds keep the graph fresh at zero cost

The builder compares the MD5 hash of the HTML before doing any work. If the prototype hasn't changed, the existing graph is reused instantly. A full rebuild of a large prototype takes ~5 seconds.

### Sanitized JSX — structure without business logic

`sanitize_jsx` strips long event handlers (`→ on[handler]`), arrow functions with bodies (`→ .[fn]`), and large ternary expressions (`→ {...}`). The agent receives the visual structure in ~20 lines instead of 400 — without losing anything relevant to implementation.

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
Component ──HAS_STYLE──────►   Style
Component ──USES_TOKEN─────►   Token
Component ──COMP_HAS_TEXT──►   UIText
Component ──HAS_INTERACTION──► Interaction
```

---

## Multiple prototypes

```bash
design-graph app-v1.html --db ~/graphs/app-v1.db
design-graph app-v2.html --db ~/graphs/app-v2.db
```

Set `GRAPH_DIR=~/graphs` in your MCP config — the server loads both automatically. Use `doc='app-v1'` or `doc='app-v2'` in tool calls to target the right one.

---

## File structure

```
.
├── build_graph.py             # HTML → Kuzu graph builder  (CLI: design-graph)
├── mcp_server.py              # MCP server                 (CLI: design-mcp)
├── query.py                   # Terminal query interface   (CLI: design-query)
├── extract_design_system.py   # Alternative: markdown extraction
├── watch_prototype.sh         # fswatch wrapper for live reload
├── Makefile                   # Convenience shortcuts
├── pyproject.toml             # Package config + CLI entry points
├── mcp-config.example.json    # MCP server configuration template
├── schema.svg                 # Graph schema diagram
└── diagram.excalidraw         # Editable diagram source
```

---

## License

MIT
