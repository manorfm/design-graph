#!/usr/bin/env python3
"""
mcp_server.py — MCP server para o grafo de design system.
JSON-RPC 2.0 over stdio. Python 3.9 compatível.
Suporta múltiplos documentos via GRAPH_DIR.

Configuração Cursor (~/.cursor/mcp.json):
{
  "mcpServers": {
    "design-system": {
      "command": "python3",
      "args": ["/Users/manoelmedeiros/Workspace/context/mcp_server.py"],
      "env": {
        "GRAPH_DIR": "/Users/manoelmedeiros/Workspace/context/graphs"
      }
    }
  }
}

Múltiplos documentos:
  build-graph ipede-v7.html  --db ~/graphs/ipede-v7.db
  build-graph outro.html     --db ~/graphs/outro.db
  → MCP busca em todos os .db dentro de GRAPH_DIR automaticamente
"""

import sys, json, os, traceback
from pathlib import Path
from _paths import resolve_graph_dir, data_dir

try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("design-graph")
except Exception:
    __version__ = "dev"

try:
    import kuzu
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "kuzu", "-q"])
    import kuzu

# Resolved at startup via layered discovery (env → config file → XDG default)
GRAPH_DIR = str(resolve_graph_dir())
GRAPH_DB  = os.environ.get("GRAPH_DB", str(data_dir() / "design-graph.db"))

# Session state — active prototype for calls that omit doc=
# Seeded from DESIGN_GRAPH_DOC env var; changeable at runtime via set_prototype tool
ACTIVE_PROTOTYPE: str = os.environ.get("DESIGN_GRAPH_DOC", "").strip()

# ─────────────────────────────────────────────────────────────────────────────
# Aliases PT/EN para busca
# ─────────────────────────────────────────────────────────────────────────────

SEARCH_ALIASES = {
    # PT → termos técnicos
    "botão": ["Btn","Button","button"],
    "botao": ["Btn","Button","button"],
    "modal": ["Modal","Dialog","Confirm","Overlay"],
    "dialogo": ["Modal","Dialog"],
    "diálogo": ["Modal","Dialog"],
    "cartão": ["Card","SectionCard","RestCard","MenuCard"],
    "cartao": ["Card","SectionCard"],
    "tabela": ["Table","DataTable","Grid"],
    "aba":    ["Tab","TabBar"],
    "abas":   ["Tab","Tabs"],
    "badge":  ["Badge","Tag","Pill","Chip"],
    "tag":    ["Badge","Tag"],
    "entrada":["Input","Field","TextField"],
    "campo":  ["Input","Field"],
    "formulario": ["Form","FormSection","SectorForm"],
    "formulário": ["Form","FormSection"],
    "menu":   ["Menu","Nav","Sidebar","Topbar"],
    "barra":  ["Bar","Header","Topbar","Nav"],
    "gaveta": ["Drawer","ProfileDrawer"],
    "painel": ["Panel","TweaksPanel","StripePanel"],
    "secao":  ["Section","SectionCard"],
    "seção":  ["Section","SectionCard"],
    "toggle": ["Toggle","Switch","SwitchRow"],
    "switch": ["Toggle","Switch"],
    "lista":  ["List","InventoryItemsList","ComponentsList"],
    "kpi":    ["KpiCard","KPI","metric"],
    "grafico":["Chart","AreaChart","DonutChart","Sparkline"],
    "gráfico":["Chart","AreaChart","DonutChart"],
    "avatar": ["Avatar","RestaurantAvatar"],
    "icone":  ["Icon","IconBtn"],
    "ícone":  ["Icon","IconBtn"],
    "cor":    ["color","primary","bg"],
    "fundo":  ["background","bg"],
    "hover":  ["hover","mouseenter"],
    "primario":["primary","#ffb81c"],
    "primário":["primary","#ffb81c"],
    # Estados
    "sucesso":["success","#22c55e"],
    "erro":   ["danger","error","#ef4444"],
    "info":   ["info","#60a5fa"],
    "premium":["premium","#a78bfa"],
}

def expand_query(query: str) -> list:
    """Returns list of search terms including aliases."""
    q = query.lower().strip()
    terms = [q]
    for alias, expansions in SEARCH_ALIASES.items():
        if alias in q:
            terms.extend(e.lower() for e in expansions)
    return list(dict.fromkeys(terms))

# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _open_db_with_retry(db_path: str, retries: int = 5, delay: float = 0.8):
    """Tenta abrir o DB com retry — Kuzu só permite uma conexão por vez."""
    import time
    last_err = None
    for attempt in range(retries):
        try:
            db   = kuzu.Database(db_path, read_only=True)
            conn = kuzu.Connection(db)
            return conn
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(delay)
    raise last_err


def open_dbs() -> list:
    """
    Returns list of (doc_name, conn).
    GRAPH_DIR is always resolved (env → config → XDG default).
    Falls back to GRAPH_DB single-file only if the directory has no .db files.
    Note: Kuzu allows only one active connection per file.
    """
    conns = []
    graph_dir = Path(GRAPH_DIR)
    if graph_dir.exists():
        for db_path in sorted(graph_dir.glob("*.db")):
            try:
                conn = _open_db_with_retry(str(db_path))
                conns.append((db_path.stem, conn))
                sys.stderr.write(f"[MCP] Loaded: {db_path.name}\n")
            except Exception as e:
                sys.stderr.write(f"[MCP] Locked: {db_path.name} — another process active? ({e})\n")
    if not conns and Path(GRAPH_DB).exists():
        try:
            conn = _open_db_with_retry(GRAPH_DB)
            conns.append((Path(GRAPH_DB).stem, conn))
            sys.stderr.write(f"[MCP] Loaded (fallback): {Path(GRAPH_DB).name}\n")
        except Exception as e:
            sys.stderr.write(f"[MCP] Failed to open DB: {e}\n")
    return conns

def q(conn, cypher: str, params: dict = None) -> list:
    result = conn.execute(cypher, params or {})
    cols   = result.get_column_names()
    rows   = []
    while result.has_next():
        rows.append(dict(zip(cols, result.get_next())))
    return rows

def q_all(conns: list, cypher: str, params: dict = None) -> list:
    """Executa query em todos os grafos e retorna resultados com campo 'doc'."""
    rows = []
    for doc_name, conn in conns:
        for row in q(conn, cypher, params):
            row["_doc"] = doc_name
            rows.append(row)
    return rows

# ─────────────────────────────────────────────────────────────────────────────
# Tool implementations
# ─────────────────────────────────────────────────────────────────────────────

def tool_list_screens(conns: list) -> str:
    lines = ["# Telas disponíveis\n"]
    for doc_name, conn in conns:
        rows = q(conn, "MATCH (s:Screen) RETURN s.name, s.component_count, s.sections_count "
                       "ORDER BY s.component_count DESC")
        if not rows:
            continue
        lines.append(f"## 📄 {doc_name}")
        for r in rows:
            comps = q(conn,
                      "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(c:Component) "
                      "RETURN c.name ORDER BY c.name LIMIT 5",
                      {"n": r["s.name"]})
            lines.append(f"**{r['s.name']}** ({r['s.component_count']} componentes)")
            if comps:
                lines.append(f"  → {', '.join(c['c.name'] for c in comps)}")
        lines.append("")
    if len(lines) == 1:
        return "Nenhuma tela encontrada. Rode build-graph primeiro."
    return "\n".join(lines)


def tool_get_screen(conn, name: str) -> str:
    screens = q(conn, "MATCH (s:Screen {name:$n}) RETURN s.name, s.component_count, s.sections_count",
                {"n": name})
    if not screens:
        all_s = q(conn, "MATCH (s:Screen) RETURN s.name")
        names_in_graph = [r["s.name"] for r in all_s]
        prefix   = [n for n in names_in_graph if n.lower().startswith(name.lower())]
        contains = [n for n in names_in_graph if name.lower() in n.lower()]
        best = prefix or contains
        if best:
            sys.stderr.write(f"[MCP] fuzzy screen: '{name}' → '{best[0]}'\n")
            return tool_get_screen(conn, best[0])
        return f"Tela '{name}' não encontrada. Use list_screens."

    s = screens[0]
    comps = q(conn,
              "MATCH (s:Screen {name:$n})-[:USES_COMPONENT]->(c:Component) "
              "RETURN c.name, c.comp_type ORDER BY c.comp_type, c.name",
              {"n": name})
    sections = q(conn,
                 "MATCH (s:Screen {name:$n})-[:HAS_SECTION]->(sec:Section) "
                 "RETURN sec.name, sec.components_json, sec.texts_json, sec.styles_json",
                 {"n": name})
    texts = q(conn,
              "MATCH (s:Screen {name:$n})-[:SCREEN_HAS_TEXT]->(t:UIText) "
              "RETURN t.content, t.text_type, t.element ORDER BY t.text_type",
              {"n": name})

    lines = [f"# Tela: {name}",
             f"Componentes: {s['s.component_count']}  |  Seções: {s['s.sections_count']}", ""]

    if sections:
        lines.append("## Seções visuais")
        for sec in sections:
            comps_in_sec = json.loads(sec["sec.components_json"] or "[]")
            texts_in_sec = json.loads(sec["sec.texts_json"] or "[]")
            styles       = json.loads(sec["sec.styles_json"] or "{}")
            lines.append(f"\n### {sec['sec.name']}")
            if comps_in_sec:
                lines.append(f"Componentes: {', '.join(comps_in_sec)}")
            if texts_in_sec:
                lines.append(f"Textos: {' | '.join(texts_in_sec[:5])}")
            if styles:
                top_styles = list(styles.items())[:4]
                lines.append(f"Estilos: {' | '.join(f'{k}:{v}' for k,v in top_styles)}")

    if comps:
        lines.append("\n## Todos os componentes")
        by_type = {}
        for c in comps:
            by_type.setdefault(c["c.comp_type"], []).append(c["c.name"])
        for t, names in sorted(by_type.items()):
            lines.append(f"**{t}**: {', '.join(names)}")

    if texts:
        lines.append("\n## Textos da UI")
        for t in texts[:20]:
            elem = f" <{t['t.element']}>" if t["t.element"] else ""
            lines.append(f"[{t['t.text_type']}{elem}] \"{t['t.content']}\"")

    return "\n".join(lines)


def tool_get_section(conn, screen: str, section: str) -> str:
    rows = q(conn,
             "MATCH (s:Screen {name:$sn})-[:HAS_SECTION]->(sec:Section) "
             "WHERE toLower(sec.name) CONTAINS toLower($sec) "
             "RETURN sec.id, sec.name, sec.styles_json, sec.components_json, "
             "       sec.texts_json, sec.jsx_snippet",
             {"sn": screen, "sec": section})

    if not rows:
        # List available sections
        available = q(conn,
                      "MATCH (s:Screen {name:$sn})-[:HAS_SECTION]->(sec:Section) "
                      "RETURN sec.name",
                      {"sn": screen})
        if available:
            sec_list = ", ".join(r["sec.name"] for r in available)
            return f"Seção '{section}' não encontrada em {screen}.\nSeções disponíveis: {sec_list}"
        return f"Nenhuma seção detectada em '{screen}'."

    sec = rows[0]
    styles     = json.loads(sec["sec.styles_json"] or "{}")
    components = json.loads(sec["sec.components_json"] or "[]")
    texts      = json.loads(sec["sec.texts_json"] or "[]")

    lines = [f"# Seção: {sec['sec.name']}  (em {screen})", ""]

    if styles:
        lines.append("## Estilos aplicados")
        for prop, val in styles.items():
            lines.append(f"- `{prop}`: `{val}`")
        lines.append("")

    if components:
        lines.append("## Componentes desta seção")
        for comp in components:
            # Get styles for each component
            comp_styles = q(conn,
                            "MATCH (c:Component {name:$n})-[:HAS_STYLE]->(s:Style) "
                            "RETURN s.state, s.property, s.value LIMIT 6",
                            {"n": comp})
            style_str = " | ".join(f"{s['s.property']}:{s['s.value']}"
                                   for s in comp_styles if s["s.state"] == "default")[:80]
            lines.append(f"- **{comp}**{': ' + style_str if style_str else ''}")
        lines.append("")

    if texts:
        lines.append("## Textos")
        for t in texts:
            lines.append(f"- \"{t}\"")
        lines.append("")

    if sec["sec.jsx_snippet"]:
        lines.append("## JSX da seção")
        lines.append("```jsx")
        lines.append(sec["sec.jsx_snippet"][:3000])
        lines.append("```")

    return "\n".join(lines)


def tool_get_component(conn, name: str) -> str:
    comps = q(conn,
              "MATCH (c:Component {name:$n}) "
              "RETURN c.name, c.comp_type, c.jsx_snippet, c.occurrence, c.classes",
              {"n": name})
    if not comps:
        all_c = q(conn, "MATCH (c:Component) RETURN c.name")
        names_in_graph = [r["c.name"] for r in all_c]
        # 1. prefix match (Btn → BtnPrimary, não MiniBtn)
        prefix = [n for n in names_in_graph if n.lower().startswith(name.lower())]
        # 2. suffix match
        suffix = [n for n in names_in_graph if n.lower().endswith(name.lower())]
        # 3. contains (último recurso)
        contains = [n for n in names_in_graph if name.lower() in n.lower()]
        best = (prefix or suffix or contains)
        if best:
            sys.stderr.write(f"[MCP] fuzzy: '{name}' → '{best[0]}'\n")
            return tool_get_component(conn, best[0])
        return f"Componente '{name}' não encontrado. Use search('{name}') para explorar."

    comp = comps[0]
    styles = q(conn,
               "MATCH (c:Component {name:$n})-[:HAS_STYLE]->(s:Style) "
               "RETURN s.state, s.property, s.value ORDER BY s.state, s.property",
               {"n": name})
    tokens = q(conn,
               "MATCH (c:Component {name:$n})-[:USES_TOKEN]->(t:Token) "
               "RETURN t.label, t.value, t.category ORDER BY t.category",
               {"n": name})
    texts = q(conn,
              "MATCH (c:Component {name:$n})-[:COMP_HAS_TEXT]->(t:UIText) "
              "RETURN t.content, t.text_type, t.element ORDER BY t.text_type",
              {"n": name})
    interactions = q(conn,
                     "MATCH (c:Component {name:$n})-[:HAS_INTERACTION]->(i:Interaction) "
                     "RETURN i.trigger, i.css_prop, i.from_val, i.to_val, i.transition",
                     {"n": name})
    screens_using = q(conn,
                      "MATCH (s:Screen)-[:USES_COMPONENT]->(c:Component {name:$n}) RETURN s.name",
                      {"n": name})

    lines = [
        f"# Componente: {name}",
        f"Tipo: **{comp['c.comp_type']}**  |  Ocorrências: {comp['c.occurrence']}",
        f"Usado em: {', '.join(r['s.name'] for r in screens_using) or 'não detectado'}",
    ]

    if comp["c.jsx_snippet"]:
        lines += ["", "## JSX (trecho do return)", "```jsx",
                  comp["c.jsx_snippet"][:4000], "```"]

    if styles:
        lines += ["", "## Estilos"]
        by_state = {}
        for s in styles:
            by_state.setdefault(s["s.state"], []).append(
                f"`{s['s.property']}`: `{s['s.value']}`")
        for state in ("default","hover","focus","transition"):
            if state in by_state:
                lines.append(f"**{state}**: {' | '.join(by_state[state][:6])}")

    if tokens:
        lines += ["", "## Tokens de design usados"]
        for t in tokens:
            lines.append(f"- **{t['t.label']}** = `{t['t.value']}` ({t['t.category']})")

    if interactions:
        lines += ["", "## Interações"]
        for i in interactions:
            lines.append(
                f"- **{i['i.trigger']}**: `{i['i.css_prop']}` "
                f"`{i['i.from_val']}` → `{i['i.to_val']}`"
                + (f"  |  transition: `{i['i.transition']}`" if i['i.transition'] else ""))

    if texts:
        lines += ["", "## Textos do componente"]
        for t in texts[:15]:
            elem = f" <{t['t.element']}>" if t["t.element"] else ""
            lines.append(f"[{t['t.text_type']}{elem}] \"{t['t.content']}\"")

    if comp["c.classes"]:
        lines += ["", f"## CSS classes: `{comp['c.classes']}`"]

    return "\n".join(lines)


def tool_get_full_jsx(conn, name: str) -> str:
    """Retorna o JSX completo de um componente ou tela, sem truncamento."""
    rows = q(conn,
             "MATCH (c:Component {name:$n}) RETURN c.jsx_snippet, c.comp_type",
             {"n": name})
    if not rows:
        rows = q(conn,
                 "MATCH (s:Screen {name:$n}) RETURN s.name",
                 {"n": name})
    jsx = rows[0].get("jsx_snippet") or rows[0].get("c.jsx_snippet", "")
    if not jsx:
        return (f"JSX completo não disponível para '{name}'.\n"
                f"Rode: make rebuild PROTO=arquivo.html")
    return f"# JSX completo: {name}\n\n```jsx\n{jsx}\n```"


def tool_get_tokens(conn, category: str = None) -> str:
    if category:
        rows = q(conn,
                 "MATCH (t:Token {category:$cat}) "
                 "RETURN t.category, t.label, t.value, t.usage ORDER BY t.usage DESC",
                 {"cat": category})
    else:
        rows = q(conn,
                 "MATCH (t:Token) "
                 "RETURN t.category, t.label, t.value, t.usage ORDER BY t.category, t.usage DESC")
    if not rows:
        return "Nenhum token encontrado."

    lines = ["# Design Tokens\n"]
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r["t.category"], []).append(r)
    for cat, tokens in sorted(by_cat.items()):
        lines.append(f"## {cat}")
        for t in tokens:
            lines.append(f"- **{t['t.label']}**: `{t['t.value']}` ({t['t.usage']} usos)")
        lines.append("")
    return "\n".join(lines)


def tool_find_token_usage(conn, value: str) -> str:
    rows = q(conn,
             "MATCH (t:Token) WHERE toLower(t.value) CONTAINS toLower($val) "
             "OR toLower(t.label) CONTAINS toLower($val) "
             "RETURN t.id, t.label, t.value, t.category",
             {"val": value})
    if not rows:
        return f"Token '{value}' não encontrado."

    lines = [f"# Uso do token: `{value}`\n"]
    for tok in rows:
        lines.append(f"## {tok['t.label']} = `{tok['t.value']}` ({tok['t.category']})")
        comps = q(conn,
                  "MATCH (c:Component)-[:USES_TOKEN]->(t:Token {id:$tid}) RETURN c.name, c.comp_type",
                  {"tid": tok["t.id"]})
        if comps:
            lines.append(f"Componentes: {', '.join(c['c.name'] for c in comps)}")
        screens = q(conn,
                    "MATCH (s:Screen)-[:USES_COMPONENT]->(c:Component)-[:USES_TOKEN]->"
                    "(t:Token {id:$tid}) RETURN DISTINCT s.name",
                    {"tid": tok["t.id"]})
        if screens:
            lines.append(f"Telas afetadas: {', '.join(s['s.name'] for s in screens)}")
        lines.append("")
    return "\n".join(lines)


def tool_search(conns: list, query: str) -> str:
    terms = expand_query(query)
    results = []
    seen_ids = set()

    for doc_name, conn in conns:
        for term in terms[:4]:
            for cypher, rtype in [
                ("MATCH (n:Screen) WHERE toLower(n.name) CONTAINS $q "
                 "RETURN 'Screen' AS type, n.name AS name, '' AS detail, n.name AS id", "Screen"),
                ("MATCH (n:Component) WHERE toLower(n.name) CONTAINS $q "
                 "RETURN 'Component' AS type, n.name AS name, n.comp_type AS detail, n.name AS id", "Component"),
                ("MATCH (n:Token) WHERE toLower(n.label) CONTAINS $q OR toLower(n.value) CONTAINS $q "
                 "RETURN 'Token' AS type, n.label AS name, n.value AS detail, n.id AS id", "Token"),
                ("MATCH (n:UIText) WHERE toLower(n.content) CONTAINS $q "
                 "RETURN 'Text' AS type, n.content AS name, n.source AS detail, n.id AS id", "UIText"),
            ]:
                for row in q(conn, cypher, {"q": term})[:4]:
                    uid = f"{doc_name}_{row['id']}"
                    if uid not in seen_ids:
                        seen_ids.add(uid)
                        row["_doc"] = doc_name
                        results.append(row)

    if not results:
        return f"Nenhum resultado para '{query}'."

    lines = [f"# Resultados para: '{query}'\n"]
    by_type = {}
    for r in results[:30]:
        by_type.setdefault(r["type"], []).append(r)
    for t, items in sorted(by_type.items()):
        lines.append(f"## {t}")
        for item in items:
            doc_tag = f" `[{item['_doc']}]`" if len(conns) > 1 else ""
            lines.append(f"- **{item['name']}**{doc_tag}" +
                         (f" — {item['detail']}" if item["detail"] else ""))
        lines.append("")
    return "\n".join(lines)


def tool_impact(conn, name: str) -> str:
    """Dado um componente ou token, retorna o que seria afetado por uma mudança."""
    if not name:
        return "Informe o nome do componente ou token. Ex: impact(name='SectionCard')"
    lines = [f"# Análise de impacto: {name}\n"]

    # É um componente?
    comp = q(conn, "MATCH (c:Component {name:$n}) RETURN c.name, c.comp_type", {"n": name})
    if comp:
        screens = q(conn,
                    "MATCH (s:Screen)-[:USES_COMPONENT]->(c:Component {name:$n}) "
                    "RETURN s.name ORDER BY s.name",
                    {"n": name})
        sections = q(conn,
                     "MATCH (sec:Section)-[:SECTION_USES]->(c:Component {name:$n}) "
                     "RETURN sec.screen, sec.name",
                     {"n": name})
        tokens_used = q(conn,
                        "MATCH (c:Component {name:$n})-[:USES_TOKEN]->(t:Token) "
                        "RETURN t.label, t.value",
                        {"n": name})
        lines.append(f"Tipo: **{comp[0]['c.comp_type']}**")
        lines.append(f"\n## Telas afetadas ({len(screens)})")
        for s in screens:
            lines.append(f"- {s['s.name']}")
        if sections:
            lines.append(f"\n## Seções afetadas ({len(sections)})")
            for sec in sections:
                lines.append(f"- {sec['sec.screen']} → {sec['sec.name']}")
        if tokens_used:
            lines.append(f"\n## Tokens que este componente usa")
            for t in tokens_used:
                lines.append(f"- **{t['t.label']}** = `{t['t.value']}`")
        return "\n".join(lines)

    # É um token?
    tok = q(conn,
            "MATCH (t:Token) WHERE t.label=$n OR t.value=$n RETURN t.id, t.label, t.value",
            {"n": name})
    if tok:
        t = tok[0]
        comps = q(conn,
                  "MATCH (c:Component)-[:USES_TOKEN]->(t:Token {id:$tid}) RETURN c.name",
                  {"tid": t["t.id"]})
        screens = q(conn,
                    "MATCH (s:Screen)-[:USES_COMPONENT]->(c:Component)-[:USES_TOKEN]->"
                    "(t:Token {id:$tid}) RETURN DISTINCT s.name",
                    {"tid": t["t.id"]})
        lines.append(f"Token: **{t['t.label']}** = `{t['t.value']}`")
        lines.append(f"\n## Componentes que usam este token ({len(comps)})")
        for c in comps:
            lines.append(f"- {c['c.name']}")
        lines.append(f"\n## Telas afetadas ({len(screens)})")
        for s in screens:
            lines.append(f"- {s['s.name']}")
        return "\n".join(lines)

    return f"'{name}' não encontrado como componente ou token. Use search() para localizar."


def tool_get_interactions(conn, name: str) -> str:
    rows = q(conn,
             "MATCH (c:Component {name:$n})-[:HAS_INTERACTION]->(i:Interaction) "
             "RETURN i.trigger, i.css_prop, i.from_val, i.to_val, i.transition",
             {"n": name})
    if not rows:
        # fuzzy
        all_c = q(conn, "MATCH (c:Component) RETURN c.name")
        matches = [r["c.name"] for r in all_c if name.lower() in r["c.name"].lower()]
        if matches and matches[0] != name:
            return tool_get_interactions(conn, matches[0])
        return f"Nenhuma interação detectada para '{name}'. O componente pode usar class toggle em vez de inline style."

    lines = [f"# Interações: {name}\n"]
    for i in rows:
        lines.append(f"**{i['i.trigger'].upper()}**")
        lines.append(f"  Propriedade: `{i['i.css_prop']}`")
        if i["i.from_val"]:
            lines.append(f"  De: `{i['i.from_val']}`")
        lines.append(f"  Para: `{i['i.to_val']}`")
        if i["i.transition"]:
            lines.append(f"  Transition: `{i['i.transition']}`")
        lines.append("")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Tool definitions (MCP schema)
# ─────────────────────────────────────────────────────────────────────────────

def _doc_param(required: bool = False) -> dict:
    """Schema fragment for the 'doc' selector parameter."""
    desc = (
        "Nome do protótipo/documento de onde buscar (ex: 'ipede-v7'). "
        "OBRIGATÓRIO quando há mais de um protótipo carregado — use list_screens "
        "para ver os nomes disponíveis. Sem isso, o primeiro protótipo é usado e "
        "você pode receber telas do projeto errado."
    )
    return {"type": "string", "description": desc}


TOOLS = [
    {
        "name": "list_screens",
        "description": (
            "Lista todas as telas de TODOS os protótipos carregados, agrupadas por documento. "
            "Use como ponto de partida: os nomes de documento retornados aqui são o valor "
            "correto para o parâmetro 'doc' das demais ferramentas."
        ),
        "inputSchema": {"type":"object","properties":{},"required":[]},
    },
    {
        "name": "get_screen",
        "description": (
            "Retorna composição completa de uma tela: seções visuais, componentes, textos e estilos. "
            "Sempre informe 'doc' para garantir que a tela é do protótipo correto."
        ),
        "inputSchema": {
            "type":"object",
            "properties": {
                "name": {"type":"string","description":"Nome da tela (ex: RestaurantsPage)"},
                "doc":  _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_section",
        "description": (
            "Retorna os detalhes visuais de uma seção específica dentro de uma tela "
            "(ex: header, filtros, lista). Sempre informe 'doc' para não misturar protótipos."
        ),
        "inputSchema": {
            "type":"object",
            "properties": {
                "screen":  {"type":"string","description":"Nome da tela"},
                "section": {"type":"string","description":"Nome ou parte do nome da seção"},
                "doc":     _doc_param(),
            },
            "required": ["screen","section"],
        },
    },
    {
        "name": "get_component",
        "description": (
            "Retorna detalhes de implementação de um componente: JSX, estilos default/hover/focus, "
            "tokens usados, textos e interações. Use antes de implementar qualquer elemento. "
            "Sempre informe 'doc' — componentes com o mesmo nome podem existir em protótipos diferentes."
        ),
        "inputSchema": {
            "type":"object",
            "properties": {
                "name": {"type":"string","description":"Nome do componente (ex: SectionCard, Btn, Modal)"},
                "doc":  _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_tokens",
        "description": (
            "Retorna os design tokens: cores e espaçamentos. Use SEMPRE antes de escrever "
            "qualquer cor ou espaçamento. Informe 'doc' para obter os tokens do protótipo correto."
        ),
        "inputSchema": {
            "type":"object",
            "properties": {
                "category": {
                    "type":"string",
                    "description":"'color' ou 'spacing'. Omita para todos.",
                    "enum":["color","spacing"],
                },
                "doc": _doc_param(),
            },
            "required": [],
        },
    },
    {
        "name": "find_token_usage",
        "description": (
            "Dado um valor ou label de token (ex: '#FFB81C', 'primary', '16px'), retorna onde é usado. "
            "Útil para análise de impacto de mudanças visuais. Informe 'doc' para escopo correto."
        ),
        "inputSchema": {
            "type":"object",
            "properties": {
                "value": {"type":"string","description":"Valor ou label do token"},
                "doc":   _doc_param(),
            },
            "required": ["value"],
        },
    },
    {
        "name": "search",
        "description": (
            "Busca em telas, componentes, tokens e textos de TODOS os protótipos. "
            "Suporta termos em português (botão, modal, tabela, seção, hover, etc.). "
            "Os resultados mostram o protótipo de origem em `[doc]` — use esse nome "
            "no parâmetro 'doc' das ferramentas de detalhe."
        ),
        "inputSchema": {
            "type":"object",
            "properties": {"query": {"type":"string","description":"Termo de busca (PT ou EN)"}},
            "required": ["query"],
        },
    },
    {
        "name": "impact",
        "description": (
            "Dado um componente ou token, retorna quais telas e seções seriam afetadas por uma mudança. "
            "Use para avaliar o risco de alterações no design system. Informe 'doc' para escopo correto."
        ),
        "inputSchema": {
            "type":"object",
            "properties": {
                "name": {"type":"string","description":"Nome do componente ou token"},
                "doc":  _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_full_jsx",
        "description": (
            "Retorna o JSX completo de um componente sem truncamento. Use quando get_component "
            "não mostrou detalhes suficientes — avatar size, ordem de campos, estrutura de abas. "
            "Informe 'doc' para garantir o protótipo correto."
        ),
        "inputSchema": {
            "type":"object",
            "properties": {
                "name": {"type":"string","description":"Nome do componente ou tela"},
                "doc":  _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_component_interactions",
        "description": (
            "Retorna os efeitos de interação (hover, focus) de um componente com propriedades "
            "e transitions. Use para implementar estados visuais corretamente. "
            "Informe 'doc' para garantir o protótipo correto."
        ),
        "inputSchema": {
            "type":"object",
            "properties": {
                "name": {"type":"string","description":"Nome do componente"},
                "doc":  _doc_param(),
            },
            "required": ["name"],
        },
    },
    {
        "name": "set_prototype",
        "description": (
            "Set the active prototype for this session. "
            "After calling this, all tools will use this prototype by default when doc= is not specified. "
            "Call with no arguments to check which prototype is currently active. "
            "The selection persists for the lifetime of the MCP server process."
        ),
        "inputSchema": {
            "type":"object",
            "properties": {
                "name": {
                    "type":"string",
                    "description":"Prototype name to activate (e.g. 'myapp'). Omit to check current selection.",
                },
            },
            "required": [],
        },
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# MCP protocol (JSON-RPC 2.0 over stdio)
# ─────────────────────────────────────────────────────────────────────────────

def send(obj: dict):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()

def _find_conn(conns: list, target: str):
    """Return conn whose name matches target (exact first, then substring)."""
    for name, conn in conns:
        if name.lower() == target.lower():
            return conn
    for name, conn in conns:
        if target.lower() in name.lower():
            return conn
    return None


def pick_conn(conns: list, doc: str = None):
    """
    Returns (conn, error_text).
    Resolution order: explicit doc= → ACTIVE_PROTOTYPE → auto-select if single.
    error_text is None on success.
    """
    if not conns:
        return None, (
            f"No graphs loaded. Build one first:\n\n"
            f"  design-graph <prototype.html>\n\n"
            f"Looking in: {GRAPH_DIR}"
        )

    # 1. Explicit doc= argument takes priority
    if doc:
        conn = _find_conn(conns, doc)
        if conn:
            return conn, None
        available = ", ".join(f"'{n}'" for n, _ in conns)
        return None, (
            f"Prototype '{doc}' not found.\n"
            f"Available: {available}\n"
            f"Use list_screens to see all loaded prototypes."
        )

    # 2. Session active prototype (set_prototype tool or DESIGN_GRAPH_DOC env)
    if ACTIVE_PROTOTYPE:
        conn = _find_conn(conns, ACTIVE_PROTOTYPE)
        if conn:
            return conn, None
        available = ", ".join(f"'{n}'" for n, _ in conns)
        return None, (
            f"Active prototype '{ACTIVE_PROTOTYPE}' not found in loaded graphs.\n"
            f"Available: {available}\n"
            f"Call set_prototype(name='...') to update the selection."
        )

    # 3. Single prototype — auto-select silently
    if len(conns) == 1:
        return conns[0][1], None

    # 4. Multiple loaded, none selected — ask for clarification
    names = ", ".join(f"'{n}'" for n, _ in conns)
    return None, (
        f"Multiple prototypes loaded: {names}\n"
        f"Call set_prototype(name='...') once to set the active prototype for this session,\n"
        f"or pass doc= to this specific call."
    )


def tool_set_prototype(conns: list, name: str) -> str:
    global ACTIVE_PROTOTYPE

    # No name → report current state
    if not name:
        if ACTIVE_PROTOTYPE:
            return f"Active prototype: '{ACTIVE_PROTOTYPE}'"
        if len(conns) == 1:
            return f"Auto-selected: '{conns[0][0]}' (only one prototype loaded — no need to set)"
        names = ", ".join(f"'{n}'" for n, _ in conns)
        return (
            f"No active prototype set.\n"
            f"Available: {names}\n"
            f"Call set_prototype(name='...') to select one."
        )

    conn = _find_conn(conns, name)
    if conn:
        matched = next(n for n, c in conns if c is conn)
        ACTIVE_PROTOTYPE = matched
        sys.stderr.write(f"[MCP] Active prototype → '{matched}'\n")
        return (
            f"Active prototype set to '{matched}'.\n"
            f"All subsequent calls without doc= will use this prototype."
        )

    available = ", ".join(f"'{n}'" for n, _ in conns)
    return f"Prototype '{name}' not found.\nAvailable: {available}"


def handle(conns: list, msg: dict):
    method = msg.get("method","")
    mid    = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        doc_names = [n for n, _ in conns]
        if not doc_names:
            description = (
                f"No graphs loaded (looking in: {GRAPH_DIR}). "
                "Run 'design-graph <prototype.html>' to build a graph, "
                "then restart the MCP server."
            )
        else:
            if ACTIVE_PROTOTYPE:
                active_line = f"Active prototype: '{ACTIVE_PROTOTYPE}' (set via DESIGN_GRAPH_DOC). "
            elif len(doc_names) == 1:
                active_line = f"Active prototype: '{doc_names[0]}' (auto-selected — only one loaded). "
            else:
                names_str = ", ".join(f"'{n}'" for n in doc_names)
                active_line = (
                    f"No active prototype set. Loaded: {names_str}. "
                    f"Call set_prototype(name='...') to select one. "
                )
            description = (
                active_line +
                "Use list_screens to explore screens, get_component for components. "
                "Pass doc= to override the active prototype for a single call."
            )
        return {"jsonrpc":"2.0","id":mid,"result":{
            "protocolVersion":"2024-11-05",
            "capabilities":{"tools":{}},
            "serverInfo":{"name":"design-graph","version":__version__,"description":description},
        }}

    if method in ("notifications/initialized","initialized"):
        return None

    if method == "tools/list":
        return {"jsonrpc":"2.0","id":mid,"result":{"tools":TOOLS}}

    if method == "tools/call":
        tool_name = params.get("name","")
        args      = params.get("arguments",{})

        # set_prototype is stateful and doesn't need a DB connection
        if tool_name == "set_prototype":
            text = tool_set_prototype(conns, args.get("name", ""))
            sys.stderr.write(f"[MCP] ✓ set_prototype → {len(text)} chars\n")
            return {"jsonrpc":"2.0","id":mid,
                    "result":{"content":[{"type":"text","text":text}]}}

        doc  = args.get("doc")
        conn, conn_err = pick_conn(conns, doc)

        # Return early with a clear message if no connection could be resolved
        if conn_err:
            sys.stderr.write(f"[MCP] ✗ {tool_name}: {conn_err[:80]}\n")
            return {"jsonrpc":"2.0","id":mid,
                    "result":{"content":[{"type":"text","text":conn_err}]}}

        # Identify which prototype is actually being used for the log
        resolved = next((n for n, c in conns if c is conn), "?")
        args_repr = ", ".join(f"{k}={repr(v)[:40]}" for k,v in args.items() if k != "doc")
        sys.stderr.write(f"[MCP] {tool_name}({args_repr}) → '{resolved}'\n")

        try:
            dispatch = {
                "list_screens":              lambda: tool_list_screens(conns),
                "get_screen":                lambda: tool_get_screen(conn, args.get("name", "")),
                "get_section":               lambda: tool_get_section(conn, args.get("screen", ""), args.get("section", "")),
                "get_component":             lambda: tool_get_component(conn, args.get("name", "")),
                "get_tokens":                lambda: tool_get_tokens(conn, args.get("category")),
                "find_token_usage":          lambda: tool_find_token_usage(conn, args.get("value", "")),
                "search":                    lambda: tool_search(conns, args.get("query", "")),
                "impact":                    lambda: tool_impact(conn, args.get("name") or args.get("component") or args.get("token", "")),
                "get_component_interactions":lambda: tool_get_interactions(conn, args.get("name", "")),
                "get_full_jsx":              lambda: tool_get_full_jsx(conn, args.get("name", "")),
            }
            fn = dispatch.get(tool_name)
            if not fn:
                text = f"Unknown tool: {tool_name}. Available: {', '.join(dispatch)}"
            else:
                text = fn()
            sys.stderr.write(f"[MCP] ✓ {tool_name} → {len(text)} chars\n")
        except Exception:
            tb = traceback.format_exc()
            sys.stderr.write(f"[MCP] ✗ {tool_name} ERRO:\n{tb}\n")
            text = f"Erro ao executar {tool_name}:\n{tb}"

        return {"jsonrpc":"2.0","id":mid,
                "result":{"content":[{"type":"text","text":text}]}}

    return {"jsonrpc":"2.0","id":mid,
            "error":{"code":-32601,"message":f"Method not found: {method}"}}


def main():
    conns = open_dbs()
    if not conns:
        sys.stderr.write(
            "[design-graph] No graphs found — starting in degraded mode.\n"
            f"  Looking in: {GRAPH_DIR}\n"
            "  Run: design-graph build <prototype.html>\n"
            "  Then restart the MCP server (or Cursor).\n"
            "  Tool calls will return setup instructions until a graph is built.\n"
        )
        # Do NOT exit — keep the server alive so the MCP client can do the
        # initialize handshake and receive a human-readable error from tool calls
        # instead of a broken-pipe / connection-refused error.
    else:
        if len(conns) == 1:
            sys.stderr.write(f"[design-graph] Started — active prototype: '{conns[0][0]}' (auto-selected)\n")
        elif ACTIVE_PROTOTYPE:
            names = ", ".join(n for n, _ in conns)
            sys.stderr.write(f"[design-graph] Started — {len(conns)} prototypes: {names} | active: '{ACTIVE_PROTOTYPE}'\n")
        else:
            names = ", ".join(n for n, _ in conns)
            sys.stderr.write(
                f"[design-graph] Started — {len(conns)} prototypes: {names}\n"
                f"  No active prototype set. Call set_prototype(name='...') to select one.\n"
            )

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(conns, msg)
        if response is not None:
            send(response)

if __name__ == "__main__":
    main()
