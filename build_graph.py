#!/usr/bin/env python3
"""
build_graph.py — Constrói/atualiza o grafo de design system no Kuzu.

Uso:
  design-graph <prototype.html> [--db <path>] [--diff] [--force]

  Sem --db: o grafo é salvo em ~/.local/share/design-graph/<nome>.db
"""

import sys, re, json, base64, gzip, hashlib, shutil
from pathlib import Path
from _paths import default_db_for
from collections import Counter, defaultdict
from datetime import datetime

try:
    from bs4 import BeautifulSoup
    import kuzu
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "beautifulsoup4", "kuzu", "-q"])
    from bs4 import BeautifulSoup
    import kuzu

# ─────────────────────────────────────────────────────────────────────────────
# Regex
# ─────────────────────────────────────────────────────────────────────────────

RE_COLOR = re.compile(
    r'#(?:[0-9a-fA-F]{3,4}){1,2}\b'
    r'|rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+(?:\s*,\s*[\d.]+)?\s*\)'
)
RE_PAGE_FN = re.compile(
    r'function ([A-Z][a-zA-Z]{2,}'
    r'(?:Page|Screen|Dashboard|Detail|Panel|View|Tab|Section|List|Form|Modal))\s*\('
)
RE_COMP_FN   = re.compile(r'function ([A-Z][a-zA-Z]{2,})\s*\(')
RE_JSX_TAG   = re.compile(r'<([A-Z][a-zA-Z]{2,})[\s/>]')
RE_COMP_REF  = re.compile(
    r'\b([A-Z][a-zA-Z]{2,}'
    r'(?:Card|Modal|Row|Tab|Panel|Form|Head|List|Table|Btn|Button|Badge|Item|'
    r'Section|Chart|Detail|View|Drawer|Widget|Dot|Pill|Select|Input|Toggle|'
    r'Switch|Avatar|Icon|Spinner|Toast|Alert|Banner))\b'
)
RE_INLINE_STYLE = re.compile(r'style=\{\{([^}]{5,600})\}\}')
RE_MOUSE_ENTER  = re.compile(r'onMouseEnter[^;]{0,60}style\.(\w+)\s*=\s*["\']([^"\']+)["\']')
RE_MOUSE_LEAVE  = re.compile(r'onMouseLeave[^;]{0,60}style\.(\w+)\s*=\s*["\']([^"\']+)["\']')
RE_TRANSITION   = re.compile(r'transition["\']?\s*:\s*["\']?([^,"\'}\n]{5,60})')
RE_UI_STRING    = re.compile(r'["\']([A-ZÁÉÍÓÚÀÂÊÎÔÛÃÕÇ][^"\']{2,80})["\']')
RE_PLACEHOLDER  = re.compile(r'placeholder[=:]\s*["\']([^"\']{3,60})["\']')
RE_SECTION_COMMENT = re.compile(r'\{/\*\s*[─━\-=*]{0,6}\s*(.{2,40?}?)\s*[─━\-=*]{0,6}\s*\*/\}')
RE_CLASS_NAME   = re.compile(r'className\s*[=:]\s*["\']([^"\']{2,120})["\']')

INTERNALS = {
    "Fragment", "Suspense", "StrictMode", "Provider", "Router", "Switch",
    "Route", "Redirect", "ErrorBoundary", "Component", "PureComponent",
    "React", "useState", "useEffect", "useRef", "useCallback", "useMemo",
    "useContext", "useReducer", "createContext", "forwardRef", "memo",
}

COLOR_LABELS = {
    "#1a1a1a": "bg_base",       "#1f1f1f": "bg_deep",
    "#2a2a2a": "bg_surface",    "#2e2e2e": "bg_elevated",
    "#333333": "bg_muted",      "#333": "bg_muted",
    "#3a3a3a": "border_default","#404040": "bg_canvas",
    "#444444": "bg_neutral",    "#444": "bg_neutral",
    "#ffb81c": "primary",       "#FFB81C": "primary",
    "#f59e0b": "primary_dim",   "#22c55e": "success",
    "#60a5fa": "info",          "#ef4444": "danger",
    "#a78bfa": "premium",       "#9ca3af": "text_muted",
    "#6b7280": "text_disabled", "#ffffff": "white",
    "#fff": "white",            "#000000": "black",
    "#262626": "bg_darker",     "#1c1c1c": "bg_darkest",
}

SCHEMA = [
    "CREATE NODE TABLE Screen(name STRING, component_count INT64, sections_count INT64, PRIMARY KEY(name))",
    "CREATE NODE TABLE Section(id STRING, screen STRING, name STRING, styles_json STRING, components_json STRING, texts_json STRING, jsx_snippet STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE Component(name STRING, comp_type STRING, jsx_snippet STRING, occurrence INT64, classes STRING, PRIMARY KEY(name))",
    "CREATE NODE TABLE Token(id STRING, category STRING, label STRING, value STRING, usage INT64, PRIMARY KEY(id))",
    "CREATE NODE TABLE UIText(id STRING, content STRING, text_type STRING, source STRING, element STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE Style(id STRING, element STRING, state STRING, property STRING, value STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE Interaction(id STRING, trigger STRING, css_prop STRING, from_val STRING, to_val STRING, transition STRING, PRIMARY KEY(id))",
    "CREATE REL TABLE USES_COMPONENT(FROM Screen TO Component)",
    "CREATE REL TABLE HAS_SECTION(FROM Screen TO Section)",
    "CREATE REL TABLE SECTION_USES(FROM Section TO Component)",
    "CREATE REL TABLE HAS_STYLE(FROM Component TO Style)",
    "CREATE REL TABLE USES_TOKEN(FROM Component TO Token)",
    "CREATE REL TABLE COMP_HAS_TEXT(FROM Component TO UIText)",
    "CREATE REL TABLE SCREEN_HAS_TEXT(FROM Screen TO UIText)",
    "CREATE REL TABLE HAS_INTERACTION(FROM Component TO Interaction)",
]

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def qrun(conn, cypher: str, params: dict = None):
    return conn.execute(cypher, params or {})

def qcount(conn, cypher: str) -> int:
    r = conn.execute(cypher)
    return r.get_next()[0] if r.has_next() else 0

def safe(conn, cypher: str, params: dict = None):
    try:
        conn.execute(cypher, params or {})
    except Exception:
        pass

def hid(s: str, prefix: str = "", length: int = 8) -> str:
    return f"{prefix}{hashlib.md5(s.encode()).hexdigest()[:length]}"

def norm_color(c: str) -> str:
    c = c.strip().lower().replace(" ", "")
    if re.match(r'^#[0-9a-f]{3}$', c):
        c = '#' + ''.join(ch * 2 for ch in c[1:])
    return c

def infer_type(name: str) -> str:
    n = name.lower()
    for k, t in [
        (["modal","dialog","confirm","alert"], "modal"),
        (["page","screen","dashboard"],        "screen"),
        (["btn","button"],                     "button"),
        (["card","tile","widget","section"],   "card"),
        (["tab","panel"],                      "tab"),
        (["form","input","field","select"],    "form"),
        (["row","item","list"],                "list-item"),
        (["badge","pill","tag","dot"],         "badge"),
        (["chart","graph","sparkline"],        "chart"),
        (["drawer","sidebar","nav"],           "navigation"),
        (["toggle","switch"],                  "toggle"),
    ]:
        if any(kw in n for kw in k):
            return t
    return "component"

# ─────────────────────────────────────────────────────────────────────────────
# Source loading
# ─────────────────────────────────────────────────────────────────────────────

def load_sources(html_path: Path) -> dict:
    html     = html_path.read_text(encoding="utf-8", errors="replace")
    soup     = BeautifulSoup(html, "html.parser")
    scripts  = soup.find_all("script")
    js_parts, inner_html = [], html

    for s in scripts:
        text = s.get_text().strip()
        if not text:
            continue

        # Large bundle map JSON: {id: {compressed, data, mime}}
        if len(text) > 10000 and text.startswith("{"):
            try:
                bundle = json.loads(text)
                if isinstance(bundle, str) and "<!DOCTYPE" in bundle:
                    inner_html = bundle
                    continue
                if isinstance(bundle, dict):
                    for val in bundle.values():
                        if not isinstance(val, dict) or not val.get("data"):
                            continue
                        try:
                            decoded = base64.b64decode(val["data"])
                            if val.get("compressed"):
                                decoded = gzip.decompress(decoded)
                            content = decoded.decode("utf-8", errors="replace")
                            if "<!DOCTYPE" in content[:200]:
                                inner_html = content
                            else:
                                js_parts.append(content)
                        except Exception:
                            pass
            except Exception:
                pass

        # Short JSON string containing inner HTML (e.g. script[3])
        elif text.startswith('"'):
            try:
                content = json.loads(text)
                if isinstance(content, str) and "<!DOCTYPE" in content:
                    inner_html = content
            except Exception:
                pass

        # Plain JS block
        elif len(text) > 500 and not text.startswith("{") and not text.startswith("["):
            js_parts.append(text)

    return {
        "js":         "\n".join(js_parts),
        "inner_html": inner_html,
        "html_hash":  hashlib.md5(html.encode()).hexdigest(),
    }

# ─────────────────────────────────────────────────────────────────────────────
# Extractors
# ─────────────────────────────────────────────────────────────────────────────

def extract_screen_map(js: str) -> dict:
    """
    Returns {screen_name: [child_component, ...]} by scanning each
    screen function's body for JSX component references.
    """
    positions = [(m.group(1), m.start(), m.end()) for m in RE_PAGE_FN.finditer(js)]
    recipes = {}
    for i, (name, _, body_start) in enumerate(positions):
        end = positions[i + 1][1] if i + 1 < len(positions) else body_start + 14000
        window = js[body_start:end]
        found = set()
        for pattern in (RE_JSX_TAG, RE_COMP_REF):
            for m in pattern.finditer(window):
                c = m.group(1)
                if c not in INTERNALS and c != name and len(c) >= 3:
                    found.add(c)
        if found:
            recipes[name] = sorted(found)
    return recipes


def extract_sections(js: str, screen_name: str) -> list:
    """
    Finds named sections inside a screen's return() by detecting
    JSX comments like {/* ── Header ── */} and extracting the
    visual block that follows each comment.
    """
    idx = js.find(f"function {screen_name}(")
    if idx < 0:
        return []
    ret = js.find("return (", idx)
    if ret < 0:
        ret = js.find("return(", idx)
    if ret < 0 or ret - idx > 20000:
        return []

    window = js[ret: ret + 16000]
    sections = []
    comment_positions = [(m.start(), m.end(), m.group(1).strip())
                         for m in RE_SECTION_COMMENT.finditer(window)]

    for i, (c_start, c_end, sec_name) in enumerate(comment_positions):
        next_start = comment_positions[i + 1][0] if i + 1 < len(comment_positions) else c_end + 4000
        block = window[c_end:next_start]

        # Styles from this section
        styles = {}
        for sm in RE_INLINE_STYLE.finditer(block):
            for prop, val in re.findall(r'(\w+)\s*:\s*["\']?([^,"\'}\n]{1,60})["\']?', sm.group(1)):
                val = val.strip().rstrip(",").strip()
                if len(val) > 1 and val not in ("true","false","null","undefined"):
                    styles[prop] = val

        # Components in this section
        comps = set()
        for pattern in (RE_JSX_TAG, RE_COMP_REF):
            for m in pattern.finditer(block):
                c = m.group(1)
                if c not in INTERNALS and len(c) >= 3:
                    comps.add(c)

        # Texts in this section
        texts = []
        seen_t = set()
        for m in RE_UI_STRING.finditer(block):
            t = m.group(1).strip()
            if t not in seen_t and 3 < len(t) < 80 and not t.startswith('#') and not t.startswith('rgba'):
                seen_t.add(t)
                texts.append(t)
        for m in RE_PLACEHOLDER.finditer(block):
            t = m.group(1).strip()
            if t not in seen_t:
                seen_t.add(t)
                texts.append(f"[placeholder] {t}")

        sections.append({
            "id":             hid(f"{screen_name}_{sec_name}", "sec_"),
            "screen":         screen_name,
            "name":           sec_name,
            "styles_json":    json.dumps(styles),
            "components_json":json.dumps(sorted(comps)),
            "texts_json":     json.dumps(texts[:15]),
            "jsx_snippet":    block[:3000].strip(),
        })

    return sections


def extract_all_components(js: str) -> Counter:
    names = RE_COMP_FN.findall(js)
    return Counter(n for n in names if n not in INTERNALS and len(n) >= 3)


def _capture_return_block(js: str, ret: int) -> str:
    """Captura o bloco return() inteiro contando parênteses."""
    # Avança até o primeiro '('
    start = js.find('(', ret)
    if start < 0 or start > ret + 10:
        return ""
    depth, i = 0, start
    limit = min(start + 40000, len(js))
    while i < limit:
        ch = js[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                return js[start + 1: i].strip()
        i += 1
    # fallback: tudo até o limite
    return js[start + 1: limit].strip()


def sanitize_jsx(jsx: str) -> str:
    """
    Remove lógica de JS do JSX mantendo apenas estrutura visual:
    - tags, hierarquia, estilos inline, textos, nomes de componentes filhos.
    Remove: handlers longos, blocos de lógica, imports, map com corpo longo.
    """
    # Handlers de evento longos → placeholder
    jsx = re.sub(
        r'on[A-Z]\w+\s*=\s*\{(?:[^{}]|\{[^{}]*\}){60,}\}',
        'on[handler]',
        jsx
    )
    # Funções arrow longas no JSX (ex: .map((x) => { muita lógica }))
    jsx = re.sub(
        r'\.\w+\s*\(\s*(?:\([^)]*\)|[\w,\s]+)\s*=>\s*\{[^}]{120,}\}',
        '.[fn]',
        jsx
    )
    # Estilos inline muito longos (>400 chars) → colapsar
    def collapse_style(m):
        inner = m.group(0)
        if len(inner) > 400:
            # manter só as primeiras propriedades
            props = re.findall(r'(\w+)\s*:\s*["\']?([^,"\'}\n]{1,40})["\']?', inner)[:6]
            preview = ', '.join(f'{k}: {v.strip()}' for k, v in props)
            return f'style={{{{ {preview}, ... }}}}'
        return inner
    jsx = re.sub(r'style=\{\{[^}]{200,}\}\}', collapse_style, jsx)
    # Expressões ternárias muito longas
    jsx = re.sub(r'\{[^{}]{300,}\}', '{...}', jsx)
    # Múltiplas linhas em branco → uma só
    jsx = re.sub(r'\n{3,}', '\n\n', jsx)
    return jsx.strip()


def extract_jsx_snippet(js: str, name: str) -> str:
    idx = js.find(f"function {name}(")
    if idx < 0:
        return ""
    ret = js.find("return (", idx)
    if ret < 0:
        ret = js.find("return(", idx)
    if ret < 0 or ret - idx > 25000:
        return ""
    raw = _capture_return_block(js, ret)
    return sanitize_jsx(raw) if raw else ""


def extract_tokens(js: str) -> list:
    colors = Counter(norm_color(c) for c in RE_COLOR.findall(js))
    skip   = {"rgba(0,0,0,0)", "transparent", "#000", "#fff", "#000000", "#ffffff"}
    tokens = []
    seen_ids = set()

    for color, count in colors.most_common(50):
        if color in skip or count < 2:
            continue
        label = COLOR_LABELS.get(color, color)
        tid = hid(color, "col_")
        if tid in seen_ids:
            continue
        seen_ids.add(tid)
        tokens.append({"id": tid, "category": "color", "label": label,
                       "value": color, "usage": count})

    spacing_re = re.compile(
        r'(?:padding|margin|gap|rowGap|columnGap)\s*[=:]\s*["\']?(\d+)(?:px)?["\']?'
    )
    spacing_vals = Counter(int(m.group(1)) for m in spacing_re.finditer(js)
                           if 2 < int(m.group(1)) < 200)
    seen_sp = set()
    for val, count in spacing_vals.most_common(16):
        if count < 2:
            continue
        rounded = round(val / 4) * 4
        if rounded in seen_sp:
            continue
        seen_sp.add(rounded)
        tokens.append({"id": f"sp_{rounded}", "category": "spacing",
                       "label": f"space_{rounded}", "value": f"{rounded}px",
                       "usage": count})

    return tokens


def build_token_map(tokens: list) -> dict:
    m = defaultdict(list)
    for t in tokens:
        m[t["value"].lower()].append(t)
    return m


def extract_styles(js: str, name: str) -> list:
    idx = js.find(f"function {name}(")
    if idx < 0:
        return []
    window = js[idx: idx + 14000]
    styles, seen = [], set()

    for sm in RE_INLINE_STYLE.finditer(window):
        for prop, val in re.findall(r'(\w+)\s*:\s*["\']?([^,"\'}\n]{1,60})["\']?', sm.group(1)):
            val = val.strip().rstrip(",").strip()
            if not val or val in ("true","false","null","undefined","inherit"):
                continue
            sid = hid(f"{name}_{prop}_{val}", "st_")
            if sid in seen:
                continue
            seen.add(sid)
            styles.append({"id": sid, "element": name, "state": "default",
                           "property": prop, "value": val})

    for m in RE_MOUSE_ENTER.finditer(window):
        sid = hid(f"{name}_hover_{m.group(1)}_{m.group(2)}", "st_")
        if sid not in seen:
            seen.add(sid)
            styles.append({"id": sid, "element": name, "state": "hover",
                           "property": m.group(1), "value": m.group(2)})

    # CSS class-based hover (e.g. onMouseEnter={e => e.currentTarget.classList.add('active')})
    for m in re.finditer(r'transition\s*:\s*["\']?([^,"\'}\n]{5,60})', window):
        val = m.group(1).strip().rstrip(",").strip()
        sid = hid(f"{name}_transition_{val}", "st_")
        if sid not in seen:
            seen.add(sid)
            styles.append({"id": sid, "element": name, "state": "transition",
                           "property": "transition", "value": val})

    return styles[:40]


def extract_interactions(js: str, name: str) -> list:
    idx = js.find(f"function {name}(")
    if idx < 0:
        return []
    window = js[idx: idx + 14000]
    interactions, seen = [], set()

    enters = re.findall(r'onMouseEnter[^;]{0,60}style\.(\w+)\s*=\s*["\']([^"\']+)["\']', window)
    leaves = re.findall(r'onMouseLeave[^;]{0,60}style\.(\w+)\s*=\s*["\']([^"\']+)["\']', window)
    trans_m = RE_TRANSITION.search(window)
    transition = trans_m.group(1).strip() if trans_m else "all 0.15s"

    for (prop, to_val), (_, from_val) in zip(enters, leaves):
        iid = hid(f"{name}_{prop}_{to_val}", "int_")
        if iid not in seen:
            seen.add(iid)
            interactions.append({"id": iid, "trigger": "hover", "css_prop": prop,
                                  "from_val": from_val, "to_val": to_val,
                                  "transition": transition})

    # Focus interactions
    for m in re.finditer(r'onFocus[^;]{0,40}style\.(\w+)\s*=\s*["\']([^"\']+)["\']', window):
        iid = hid(f"{name}_focus_{m.group(1)}", "int_")
        if iid not in seen:
            seen.add(iid)
            interactions.append({"id": iid, "trigger": "focus", "css_prop": m.group(1),
                                  "from_val": "", "to_val": m.group(2),
                                  "transition": transition})

    return interactions[:15]


def extract_texts(js: str, name: str) -> list:
    idx = js.find(f"function {name}(")
    if idx < 0:
        return []
    window = js[idx: idx + 14000]
    texts, seen = [], set()

    # Detect element context for better classification
    HEADING_RE  = re.compile(r'<h[1-6][^>]*>\s*["\']?([^<"\']{3,60})')
    BUTTON_RE   = re.compile(r'<(?:button|Btn)[^>]*>\s*["\']?([^<"\']{2,40})')
    LABEL_RE    = re.compile(r'<(?:label|span)[^>]*>\s*["\']?([^<"\']{3,60})')

    def add(content, text_type, element=""):
        c = content.strip()
        if c in seen or len(c) < 3 or len(c) > 80:
            return
        if re.match(r'^[a-z_]+$', c) or c.startswith('#') or c.startswith('rgba'):
            return
        seen.add(c)
        texts.append({"id": hid(f"{name}_{c}", "txt_"), "content": c,
                      "text_type": text_type, "source": name, "element": element})

    for m in HEADING_RE.finditer(window):   add(m.group(1), "heading",     "h")
    for m in BUTTON_RE.finditer(window):    add(m.group(1), "button",      "button")
    for m in LABEL_RE.finditer(window):     add(m.group(1), "label",       "label")
    for m in RE_PLACEHOLDER.finditer(window): add(m.group(1), "placeholder", "input")

    # Generic strings
    for m in RE_UI_STRING.finditer(window):
        t = m.group(1).strip()
        text_type = "description" if len(t) > 40 else "label"
        add(t, text_type, "")

    return texts[:30]


# ─────────────────────────────────────────────────────────────────────────────
# State (incremental diff)
# ─────────────────────────────────────────────────────────────────────────────

def load_state(state_path: Path) -> dict:
    if state_path.exists():
        try:
            return json.loads(state_path.read_text())
        except Exception:
            pass
    return {"html_hash": "", "screens": {}, "components": {}, "last_build": ""}

def save_state(state_path: Path, state: dict):
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))

def compute_entity_hash(data: dict) -> str:
    return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]

def diff_state(prev: dict, curr_screens: dict, curr_comps: Counter) -> dict:
    prev_screens = set(prev.get("screens", {}).keys())
    curr_screen_names = set(curr_screens.keys())
    prev_comps = set(prev.get("components", {}).keys())
    curr_comp_names = set(curr_comps.keys())
    return {
        "screens_added":   sorted(curr_screen_names - prev_screens),
        "screens_removed": sorted(prev_screens - curr_screen_names),
        "comps_added":     sorted(curr_comp_names - prev_comps),
        "comps_removed":   sorted(prev_comps - curr_comp_names),
        "is_first_build":  not prev.get("html_hash"),
    }

# ─────────────────────────────────────────────────────────────────────────────
# Graph builder
# ─────────────────────────────────────────────────────────────────────────────

def build(html_path: Path, db_path: Path, show_diff: bool = False):
    state_path = db_path.parent / ".graph-state.json"
    prev_state = load_state(state_path)

    print(f"\n{'─'*55}")
    print(f"  Prototype : {html_path.name}")
    print(f"  Graph DB  : {db_path}")
    print(f"{'─'*55}")

    print("\n[1/5] Carregando prototype...")
    sources   = load_sources(html_path)
    js        = sources["js"]
    html_hash = sources["html_hash"]

    if prev_state["html_hash"] == html_hash:
        print("  Prototype não mudou desde o último build. Use --force para forçar.")
        return

    print(f"  JS total: {len(js):,} chars")

    print("\n[2/5] Extraindo entidades...")
    screen_map  = extract_screen_map(js)
    all_comps   = extract_all_components(js)
    tokens      = extract_tokens(js)
    token_map   = build_token_map(tokens)

    print(f"  Telas: {len(screen_map)} | Componentes: {len(all_comps)} | Tokens: {len(tokens)}")

    # Diff
    d = diff_state(prev_state, screen_map, all_comps)
    if show_diff and not d["is_first_build"]:
        if d["screens_added"]:   print(f"  + Telas novas: {', '.join(d['screens_added'])}")
        if d["screens_removed"]: print(f"  - Telas removidas: {', '.join(d['screens_removed'])}")
        if d["comps_added"]:     print(f"  + Componentes novos: {len(d['comps_added'])}")
        if d["comps_removed"]:   print(f"  - Componentes removidos: {len(d['comps_removed'])}")

    print("\n[3/5] Recriando banco de dados...")
    if db_path.exists():
        # Kuzu may store the DB as a directory (newer) or a file (older builds)
        if db_path.is_dir():
            shutil.rmtree(str(db_path), ignore_errors=True)
        else:
            db_path.unlink(missing_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db   = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    for stmt in SCHEMA:
        conn.execute(stmt)

    print("\n[4/5] Inserindo nós e relacionamentos...")

    # ── Tokens ──
    for t in tokens:
        safe(conn,
             "CREATE (:Token {id:$id,category:$cat,label:$lbl,value:$val,usage:$use})",
             {"id":t["id"],"cat":t["category"],"lbl":t["label"],"val":t["value"],"use":t["usage"]})

    # ── Componentes ──
    inserted_comps   = set()
    inserted_style_ids = set()
    inserted_inter_ids = set()
    inserted_text_ids  = set()
    token_rels_done    = set()

    for comp_name, occ in all_comps.most_common():
        if comp_name in INTERNALS:
            continue
        snippet   = extract_jsx_snippet(js, comp_name)
        comp_type = infer_type(comp_name)
        fn_idx = js.find(f"function {comp_name}(")
        fn_window = js[fn_idx: fn_idx + 8000] if fn_idx >= 0 else ""
        classes = " ".join(list(dict.fromkeys(RE_CLASS_NAME.findall(fn_window)))[:10])

        safe(conn,
             "CREATE (:Component {name:$n,comp_type:$t,jsx_snippet:$s,occurrence:$o,classes:$c})",
             {"n":comp_name,"t":comp_type,"s":snippet,"o":occ,"c":classes})
        inserted_comps.add(comp_name)

        for st in extract_styles(js, comp_name):
            if st["id"] in inserted_style_ids:
                continue
            inserted_style_ids.add(st["id"])
            safe(conn, "CREATE (:Style {id:$id,element:$el,state:$st,property:$pr,value:$vl})",
                 {"id":st["id"],"el":st["element"],"st":st["state"],"pr":st["property"],"vl":st["value"]})
            safe(conn,
                 "MATCH (c:Component {name:$cn}),(s:Style {id:$sid}) CREATE (c)-[:HAS_STYLE]->(s)",
                 {"cn":comp_name,"sid":st["id"]})
            for tok in token_map.get(st["value"].lower(), []):
                rel_key = f"{comp_name}_{tok['id']}"
                if rel_key not in token_rels_done:
                    token_rels_done.add(rel_key)
                    safe(conn,
                         "MATCH (c:Component {name:$cn}),(t:Token {id:$tid}) CREATE (c)-[:USES_TOKEN]->(t)",
                         {"cn":comp_name,"tid":tok["id"]})

        for inter in extract_interactions(js, comp_name):
            if inter["id"] in inserted_inter_ids:
                continue
            inserted_inter_ids.add(inter["id"])
            safe(conn,
                 "CREATE (:Interaction {id:$id,trigger:$tr,css_prop:$pr,from_val:$fv,to_val:$tv,transition:$tn})",
                 {"id":inter["id"],"tr":inter["trigger"],"pr":inter["css_prop"],
                  "fv":inter["from_val"],"tv":inter["to_val"],"tn":inter["transition"]})
            safe(conn,
                 "MATCH (c:Component {name:$cn}),(i:Interaction {id:$iid}) CREATE (c)-[:HAS_INTERACTION]->(i)",
                 {"cn":comp_name,"iid":inter["id"]})

        for txt in extract_texts(js, comp_name):
            if txt["id"] in inserted_text_ids:
                continue
            inserted_text_ids.add(txt["id"])
            safe(conn,
                 "CREATE (:UIText {id:$id,content:$ct,text_type:$ty,source:$src,element:$el})",
                 {"id":txt["id"],"ct":txt["content"],"ty":txt["text_type"],
                  "src":txt["source"],"el":txt["element"]})
            safe(conn,
                 "MATCH (c:Component {name:$cn}),(t:UIText {id:$tid}) CREATE (c)-[:COMP_HAS_TEXT]->(t)",
                 {"cn":comp_name,"tid":txt["id"]})

    # ── Telas e seções ──
    screen_rel_done = set()
    for screen_name, children in screen_map.items():
        sections = extract_sections(js, screen_name)
        safe(conn,
             "CREATE (:Screen {name:$n,component_count:$cc,sections_count:$sc})",
             {"n":screen_name,"cc":len(children),"sc":len(sections)})

        # Ensure all child components exist
        for comp in children:
            if comp not in inserted_comps:
                safe(conn,
                     "CREATE (:Component {name:$n,comp_type:$t,jsx_snippet:$s,occurrence:$o,classes:$c})",
                     {"n":comp,"t":infer_type(comp),"s":"","o":1,"c":""})
                inserted_comps.add(comp)
            rel_key = f"{screen_name}→{comp}"
            if rel_key not in screen_rel_done:
                screen_rel_done.add(rel_key)
                safe(conn,
                     "MATCH (s:Screen {name:$sn}),(c:Component {name:$cn}) CREATE (s)-[:USES_COMPONENT]->(c)",
                     {"sn":screen_name,"cn":comp})

        # Sections
        for sec in sections:
            safe(conn,
                 "CREATE (:Section {id:$id,screen:$sc,name:$nm,styles_json:$sj,components_json:$cj,texts_json:$tj,jsx_snippet:$jsx})",
                 {"id":sec["id"],"sc":sec["screen"],"nm":sec["name"],"sj":sec["styles_json"],
                  "cj":sec["components_json"],"tj":sec["texts_json"],"jsx":sec["jsx_snippet"]})
            safe(conn,
                 "MATCH (s:Screen {name:$sn}),(sec:Section {id:$sid}) CREATE (s)-[:HAS_SECTION]->(sec)",
                 {"sn":screen_name,"sid":sec["id"]})
            for comp in json.loads(sec["components_json"]):
                if comp not in inserted_comps:
                    safe(conn,
                         "CREATE (:Component {name:$n,comp_type:$t,jsx_snippet:$s,occurrence:$o,classes:$c})",
                         {"n":comp,"t":infer_type(comp),"s":"","o":1,"c":""})
                    inserted_comps.add(comp)
                safe(conn,
                     "MATCH (sec:Section {id:$sid}),(c:Component {name:$cn}) CREATE (sec)-[:SECTION_USES]->(c)",
                     {"sid":sec["id"],"cn":comp})

        # Texts from screen
        for txt in extract_texts(js, screen_name):
            if txt["id"] in inserted_text_ids:
                continue
            inserted_text_ids.add(txt["id"])
            safe(conn,
                 "CREATE (:UIText {id:$id,content:$ct,text_type:$ty,source:$src,element:$el})",
                 {"id":txt["id"],"ct":txt["content"],"ty":txt["text_type"],
                  "src":txt["source"],"el":txt["element"]})
            safe(conn,
                 "MATCH (s:Screen {name:$sn}),(t:UIText {id:$tid}) CREATE (s)-[:SCREEN_HAS_TEXT]->(t)",
                 {"sn":screen_name,"tid":txt["id"]})

    # ── Stats ──
    print("\n[5/5] Finalizando...")
    sc = qcount(conn, "MATCH (n:Screen) RETURN count(n)")
    cc = qcount(conn, "MATCH (n:Component) RETURN count(n)")
    tc = qcount(conn, "MATCH (n:Token) RETURN count(n)")
    tx = qcount(conn, "MATCH (n:UIText) RETURN count(n)")
    st = qcount(conn, "MATCH (n:Style) RETURN count(n)")
    se = qcount(conn, "MATCH (n:Section) RETURN count(n)")
    ic = qcount(conn, "MATCH (n:Interaction) RETURN count(n)")

    print(f"\n{'─'*55}")
    print(f"  Screens:      {sc:>4}    Sections:   {se:>4}")
    print(f"  Components:   {cc:>4}    Tokens:     {tc:>4}")
    print(f"  UITexts:      {tx:>4}    Styles:     {st:>4}")
    print(f"  Interactions: {ic:>4}")
    print(f"{'─'*55}")
    print(f"  Grafo salvo em: {db_path}")

    # Save diff report
    if not d["is_first_build"] and show_diff:
        report_path = db_path.parent / "graph-diff.md"
        lines = [
            f"# Graph Diff — {datetime.now().isoformat()}",
            "",
            f"## Telas",
            f"- Adicionadas: {', '.join(d['screens_added']) or 'nenhuma'}",
            f"- Removidas: {', '.join(d['screens_removed']) or 'nenhuma'}",
            "",
            f"## Componentes",
            f"- Adicionados: {len(d['comps_added'])} ({', '.join(d['comps_added'][:10])})",
            f"- Removidos: {len(d['comps_removed'])} ({', '.join(d['comps_removed'][:10])})",
        ]
        report_path.write_text("\n".join(lines))
        print(f"  Diff salvo em: {report_path}")

    # Update state
    new_state = {
        "html_hash":  html_hash,
        "last_build": datetime.now().isoformat(),
        "screens":    {n: compute_entity_hash({"name": n, "children": c})
                       for n, c in screen_map.items()},
        "components": {n: occ for n, occ in all_comps.most_common(200)},
    }
    save_state(state_path, new_state)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    html_path  = Path(args[0])
    show_diff  = "--diff" in args
    force      = "--force" in args

    # Default: central XDG directory, named after the prototype
    db_path = default_db_for(html_path.stem)

    for a in args[1:]:
        if not a.startswith("--"):
            db_path = Path(a)
            break
    if "--db" in args:
        db_path = Path(args[args.index("--db") + 1]).expanduser()

    if not html_path.exists():
        print(f"Erro: arquivo não encontrado: {html_path}")
        sys.exit(1)

    if force:
        state_path = db_path.parent / ".graph-state.json"
        if state_path.exists():
            state_path.unlink()

    build(html_path, db_path, show_diff=show_diff)


if __name__ == "__main__":
    main()
