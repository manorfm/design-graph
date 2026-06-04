#!/usr/bin/env python3
"""
Design System Extractor — iPede / qualquer prototype HTML
Suporta: plain HTML, React bundled (gzip/base64), Tailwind, CSS-in-JS

Uso:
  python3 extract_design_system.py prototype.html          # extração única
  python3 extract_design_system.py prototype.html --watch  # re-roda ao salvar
  python3 extract_design_system.py prototype.html --merge  # preserva edições manuais
"""

import sys, re, json, base64, gzip, hashlib, time, subprocess, shutil
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime

try:
    from bs4 import BeautifulSoup
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "beautifulsoup4", "-q"])
    from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────────────────────────
# Patterns
# ─────────────────────────────────────────────────────────────────────────────

RE_COLOR = re.compile(
    r'#(?:[0-9a-fA-F]{3,4}){1,2}\b'
    r'|rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+(?:\s*,\s*[\d.]+)?\s*\)'
    r'|hsla?\(\s*\d+\s*,\s*[\d.]+%\s*,\s*[\d.]+%(?:\s*,\s*[\d.]+)?\s*\)'
)
RE_PX          = re.compile(r'\b(\d*\.?\d+)(px|rem|em|%|vh|vw)\b')
RE_SHADOW      = re.compile(r'(?:box|text)-?shadow\s*[=:]\s*["\']?([^;}{"\'\n]{10,})')
RE_RADIUS      = re.compile(r'border-?[Rr]adius\s*[=:]\s*["\']?([^;}{"\'\n]{2,30})')
RE_FONT_FAM    = re.compile(r"font-?[Ff]amily\s*[=:]\s*[\"']?([^;}{\"'\n]{5,80})")
RE_FONT_SIZE   = re.compile(r"font-?[Ss]ize\s*[=:]\s*[\"']?([^;}{\"'\n]{2,20})")
RE_FONT_WEIGHT = re.compile(r"font-?[Ww]eight\s*[=:]\s*[\"']?(\d{3,4}|bold|semibold)")
RE_CSS_VAR     = re.compile(r'--[\w-]+\s*:\s*[^;}{]+')
RE_SPACING     = re.compile(
    r'(?:margin|padding|gap|rowGap|columnGap|marginTop|marginBottom|marginLeft|marginRight'
    r'|paddingTop|paddingBottom|paddingLeft|paddingRight)\s*[=:]\s*["\']?([^;}{"\'\n]{1,30})'
)
RE_REACT_COMP  = re.compile(r'function ([A-Z][a-zA-Z]{2,}(?:Screen|View|Page|Panel|Modal|Tab|Section|Dashboard|List|Detail|Form|Card|Row|Item|Header|Footer|Sidebar|Nav|Menu|Table|Grid|Chart|Widget|Button|Btn|Badge|Tag))\s*\(')
RE_CLASS_NAME  = re.compile(r'className\s*[=:]\s*["\']([^"\']{2,120})["\']')

SEMANTIC_KEYWORDS = {
    "navbar":     ["nav", "navbar", "topbar", "navigation", "header"],
    "sidebar":    ["sidebar", "sidenav", "aside", "drawer"],
    "card":       ["card", "tile", "widget", "panel", "box"],
    "table":      ["table", "data-table", "grid"],
    "form":       ["form", "form-group", "field", "input-group"],
    "modal":      ["modal", "dialog", "popup", "overlay"],
    "button":     ["btn", "button", "cta"],
    "badge":      ["badge", "tag", "chip", "label", "pill"],
    "alert":      ["alert", "notification", "toast", "banner"],
    "tabs":       ["tab", "tabs", "tabbar"],
    "dropdown":   ["dropdown", "select-menu"],
    "pagination": ["pagination", "pager"],
    "avatar":     ["avatar", "profile-pic", "user-icon"],
    "kpi":        ["kpi", "stat", "metric", "counter", "summary-card"],
    "chart":      ["chart", "graph", "plot"],
}

# ─────────────────────────────────────────────────────────────────────────────
# Format detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_format(html: str, soup) -> str:
    scripts = soup.find_all("script")
    for s in scripts:
        text = s.get_text()
        # JSON with base64/compressed bundles
        if len(text) > 50000 and re.search(r'"compressed"\s*:\s*true', text):
            return "bundled_react"
        # Large minified JS
        if len(text) > 100000 and "createElement" in text:
            return "bundled_react"

    style_text = " ".join(t.get_text() for t in soup.find_all("style"))
    # Tailwind detection
    if re.search(r'\.(?:flex|grid|p-\d|m-\d|text-|bg-|border-)\s*\{', style_text):
        return "tailwind"

    return "plain_html"


# ─────────────────────────────────────────────────────────────────────────────
# Source extraction per format
# ─────────────────────────────────────────────────────────────────────────────

def get_sources(html: str, soup, fmt: str) -> dict:
    """Returns dict with keys: css (str), js (str), inner_html (str)"""
    css_parts, js_parts, inner_html = [], [], html

    if fmt == "bundled_react":
        scripts = soup.find_all("script")
        for s in scripts:
            text = s.get_text().strip()
            # Compressed bundle JSON
            if len(text) > 10000 and "{" == text[0]:
                try:
                    bundle = json.loads(text)
                    # Could be the inner HTML string
                    if isinstance(bundle, str) and "<!DOCTYPE" in bundle:
                        inner_html = bundle
                        inner_soup = BeautifulSoup(bundle, "html.parser")
                        for st in inner_soup.find_all("style"):
                            css_parts.append(st.get_text())
                        continue
                    # Bundle map {id: {compressed, data, mime}}
                    if isinstance(bundle, dict):
                        for key, val in bundle.items():
                            if not isinstance(val, dict):
                                continue
                            mime = val.get("mime", "")
                            raw_data = val.get("data", "")
                            if not raw_data:
                                continue
                            try:
                                decoded = base64.b64decode(raw_data)
                                if val.get("compressed"):
                                    decoded = gzip.decompress(decoded)
                                content = decoded.decode("utf-8", errors="replace")
                            except Exception:
                                continue
                            if "javascript" in mime or mime == "":
                                js_parts.append(content)
                            elif "css" in mime:
                                css_parts.append(content)
                            # Check if it's the inner HTML
                            elif "html" in mime or ("<!DOCTYPE" in content):
                                inner_html = content
                                inner_soup = BeautifulSoup(content, "html.parser")
                                for st in inner_soup.find_all("style"):
                                    css_parts.append(st.get_text())
                except Exception:
                    pass
            # Plain JS in script tag
            elif len(text) > 1000 and not text.startswith("{"):
                js_parts.append(text)

    else:
        # Plain HTML: collect <style> tags and inline styles
        for tag in soup.find_all("style"):
            css_parts.append(tag.get_text())
        for tag in soup.find_all(style=True):
            css_parts.append(tag["style"])
        for s in soup.find_all("script"):
            js_parts.append(s.get_text())

    return {
        "css": "\n".join(css_parts),
        "js":  "\n".join(js_parts),
        "inner_html": inner_html,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Extractors
# ─────────────────────────────────────────────────────────────────────────────

def norm_color(c: str) -> str:
    c = c.strip().lower().replace(" ", "")
    if re.match(r'^#[0-9a-f]{3}$', c):
        c = '#' + ''.join(ch*2 for ch in c[1:])
    return c

def extract_colors(sources: dict) -> Counter:
    combined = sources["css"] + "\n" + sources["js"]
    raw = RE_COLOR.findall(combined)
    counts = Counter(norm_color(c) for c in raw)
    # Remove transparent / fully-black-alpha / white variants with very low usage
    skip = {"rgba(0,0,0,0)", "transparent", "#000", "#fff", "#000000", "#ffffff"}
    return Counter({c: n for c, n in counts.items() if c not in skip and n > 1})

def extract_spacing(sources: dict) -> list:
    combined = sources["css"] + "\n" + sources["js"]
    values = []
    for m in RE_SPACING.finditer(combined):
        for sm in RE_PX.finditer(m.group(1)):
            v, unit = sm.groups()
            if unit == "px":
                values.append(int(float(v)))
    counts = Counter(values)
    raw = sorted({int(round(v / 4) * 4) for v, n in counts.items() if n > 1 and 2 < v < 200})
    return raw

def extract_typography(sources: dict) -> dict:
    combined = sources["css"] + "\n" + sources["js"]
    families = [m.group(1).strip().rstrip(";,").strip() for m in RE_FONT_FAM.finditer(combined)]
    sizes    = [m.group(1).strip().rstrip(";").strip()   for m in RE_FONT_SIZE.finditer(combined)]
    weights  = [m.group(1).strip()                        for m in RE_FONT_WEIGHT.finditer(combined)]
    return {
        "families": [f for f, _ in Counter(families).most_common(3)],
        "sizes":    [s for s, n in Counter(sizes).most_common() if n > 1][:10],
        "weights":  sorted(set(weights)),
    }

def extract_shadows(sources: dict) -> list:
    combined = sources["css"] + "\n" + sources["js"]
    raw = [m.group(1).strip().rstrip(";,'\"") for m in RE_SHADOW.finditer(combined)]
    counts = Counter(raw)
    return [s for s, _ in counts.most_common() if s and s != "none"][:8]

def extract_radii(sources: dict) -> list:
    combined = sources["css"] + "\n" + sources["js"]
    values = []
    for m in RE_RADIUS.finditer(combined):
        for sm in RE_PX.finditer(m.group(1)):
            values.append(f"{sm.group(1)}{sm.group(2)}")
    counts = Counter(values)
    return [r for r, n in counts.most_common() if n > 1][:8]

def extract_css_vars(sources: dict) -> dict:
    combined = sources["css"] + "\n" + sources["js"]
    result = {}
    for m in RE_CSS_VAR.finditer(combined):
        raw = m.group(0).strip()
        if ":" in raw:
            name, _, val = raw.partition(":")
            result[name.strip()] = val.strip().rstrip(";")
    return result

def extract_animations(sources: dict) -> dict:
    combined = sources["css"] + "\n" + sources["js"]
    names = re.findall(r'@keyframes\s+([\w-]+)', combined)
    return {n: True for n in set(names)}

def extract_components_from_html(soup) -> dict:
    found = defaultdict(list)
    for tag in soup.find_all(True):
        classes = " ".join(tag.get("class", [])).lower()
        tag_name = (tag.name or "").lower()
        for comp, keywords in SEMANTIC_KEYWORDS.items():
            for kw in keywords:
                if kw in classes or (comp == "table" and tag_name == "table"):
                    found[comp].append(tag)
                    break
    # Deduplicate
    result = {}
    for comp, nodes in found.items():
        seen, unique = set(), []
        for n in nodes:
            key = str(n)[:100]
            if key not in seen:
                seen.add(key)
                unique.append(n)
        result[comp] = unique
    return result

def extract_components_from_js(sources: dict) -> list:
    matches = RE_REACT_COMP.findall(sources["js"])
    # Also find class-based components
    class_comps = re.findall(r'class ([A-Z][a-zA-Z]{2,}) extends (?:React\.)?(?:Pure)?Component', sources["js"])
    all_comps = list(dict.fromkeys(matches + class_comps))
    # Filter out React internals
    internals = {"Component", "PureComponent", "ReactDOM", "FiberNode", "FiberRootNode",
                 "SyntheticBaseEvent", "ChildReconciler", "Generator", "AsyncGenerator",
                 "ReactDOMRoot", "ReactDOMHydrationRoot"}
    return [c for c in all_comps if c not in internals and len(c) > 3]

def extract_classname_system(sources: dict) -> dict:
    """Detect CSS class naming conventions (BEM, utility prefixes, etc.)"""
    all_classes = RE_CLASS_NAME.findall(sources["js"] + sources["css"])
    flat = []
    for cls_str in all_classes:
        flat.extend(cls_str.split())

    counter = Counter(flat)
    # Detect prefix patterns
    prefixes = Counter()
    for cls in flat:
        if "-" in cls:
            prefix = cls.split("-")[0]
            if len(prefix) > 1:
                prefixes[prefix] += 1

    return {
        "top_classes": [c for c, _ in counter.most_common(20)],
        "top_prefixes": [p for p, n in prefixes.most_common(5) if n > 2],
    }

def extract_composition(sources: dict) -> dict:
    """
    Para cada Page/Screen/Dashboard, extrai quais componentes ela monta.
    Suporta JSX direto (<Component />) e chamadas jsx(Component, ...).
    Resultado: {"RestaurantsPage": ["PageHead", "RestCard", "ConfirmModal", ...]}
    """
    js = sources["js"]
    page_re = re.compile(
        r'function ([A-Z][a-zA-Z]{2,}(?:Page|Screen|Dashboard|Detail|Panel|View))\s*\('
    )
    # JSX tag: <ComponentName  ou <ComponentName>
    jsx_tag_re  = re.compile(r'<([A-Z][a-zA-Z]{2,})[\s/>]')
    # Transpiled: jsx(ComponentName, ou jsxs(ComponentName,
    jsx_call_re = re.compile(r'jsxs?\(([A-Z][a-zA-Z]{2,})\s*,')
    # Referência direta: ComponentName( ou {ComponentName}
    ref_re = re.compile(
        r'\b([A-Z][a-zA-Z]{2,}(?:Card|Modal|Row|Tab|Panel|Form|Head|List|Table|Btn|Button|Badge|Item|Section|Chart|Detail|View))\b'
    )
    internals = {
        "Fragment", "Suspense", "StrictMode", "Provider", "Router",
        "Switch", "Route", "Redirect", "ErrorBoundary", "Component",
        "PureComponent", "React", "useState", "useEffect", "useRef",
        "useCallback", "useMemo", "useContext",
    }

    # Localizar onde cada função de tela começa e termina
    page_positions = []
    for m in page_re.finditer(js):
        page_positions.append((m.group(1), m.start(), m.end()))

    recipes = {}
    for i, (name, start, body_start) in enumerate(page_positions):
        # Fim = início da próxima função de tela (ou 12000 chars)
        end = page_positions[i + 1][1] if i + 1 < len(page_positions) else body_start + 12000
        window = js[body_start:end]

        found = set()
        for r in (jsx_tag_re, jsx_call_re, ref_re):
            for m in r.finditer(window):
                c = m.group(1)
                if c not in internals and c != name:
                    found.add(c)

        if found:
            recipes[name] = sorted(found)

    return recipes


def detect_shell_violations(recipes: dict) -> list:
    """Pages that render without any shell/layout wrapper."""
    shell_keywords = {"Shell", "Layout", "AppShell", "Page", "Wrapper",
                      "Container", "Frame", "Sidebar", "Nav"}
    violations = []
    for page, children in recipes.items():
        uses_shell = any(
            any(kw.lower() in c.lower() for kw in shell_keywords)
            for c in children
        )
        if not uses_shell and children:
            violations.append({"page": page, "mounts": children})
    return violations


def detect_layouts(soup, sources: dict) -> list:
    layouts = []
    css = sources["css"] + sources["js"]
    inner = sources["inner_html"]
    inner_soup = BeautifulSoup(inner, "html.parser") if inner != "" else soup

    has_sidebar  = bool(inner_soup.find(class_=re.compile(r'sidebar|sidenav', re.I)))
    has_header   = bool(inner_soup.find(["header", "nav"]) or inner_soup.find(class_=re.compile(r'header|navbar|topbar', re.I)))
    has_footer   = bool(inner_soup.find("footer") or inner_soup.find(class_=re.compile(r'footer', re.I)))
    has_grid     = bool(re.search(r'display\s*[=:]\s*["\']?grid', css))
    has_flex     = bool(re.search(r'display\s*[=:]\s*["\']?flex', css))
    has_tabs     = bool(inner_soup.find(class_=re.compile(r'\btab', re.I)) or "Tab" in sources["js"])
    has_modal    = bool(inner_soup.find(class_=re.compile(r'modal|dialog', re.I)) or "Modal" in sources["js"])
    has_drawer   = bool(re.search(r'translateX', css))
    has_dashboard = bool(re.search(r'Dashboard|dashboard', sources["js"]))

    if has_header and has_sidebar:
        layouts.append({"name": "App Shell (header + sidebar + main)", "confidence": "high"})
    elif has_header:
        layouts.append({"name": "Top-nav layout (header + content)", "confidence": "high"})
    if has_tabs:
        layouts.append({"name": "Tabbed page layout", "confidence": "high"})
    if has_modal:
        layouts.append({"name": "Modal overlay pattern", "confidence": "high"})
    if has_drawer:
        layouts.append({"name": "Slide-in drawer pattern", "confidence": "high"})
    if has_dashboard:
        layouts.append({"name": "Dashboard with KPI cards", "confidence": "medium"})
    if has_grid:
        layouts.append({"name": "CSS Grid layout", "confidence": "medium"})
    if has_flex:
        layouts.append({"name": "Flexbox primary layout", "confidence": "high"})
    if has_footer:
        layouts.append({"name": "Page with sticky footer", "confidence": "medium"})

    return layouts


# ─────────────────────────────────────────────────────────────────────────────
# State management (enables improvement over time)
# ─────────────────────────────────────────────────────────────────────────────

def load_state(state_path: Path) -> dict:
    if state_path.exists():
        try:
            return json.loads(state_path.read_text())
        except Exception:
            pass
    return {"runs": 0, "color_counts": {}, "component_counts": {}, "html_hash": ""}

def save_state(state_path: Path, state: dict):
    state_path.write_text(json.dumps(state, indent=2))

def accumulate_state(state: dict, colors: Counter, components: list) -> dict:
    """Each run, color and component counts accumulate — higher = more confident."""
    state["runs"] = state.get("runs", 0) + 1
    state["last_run"] = datetime.now().isoformat()

    cc = state.get("color_counts", {})
    for c, n in colors.items():
        cc[c] = cc.get(c, 0) + n
    state["color_counts"] = cc

    comp_c = state.get("component_counts", {})
    for c in components:
        comp_c[c] = comp_c.get(c, 0) + 1
    state["component_counts"] = comp_c

    return state


# ─────────────────────────────────────────────────────────────────────────────
# Merge helper (preserve manual additions)
# ─────────────────────────────────────────────────────────────────────────────

MANUAL_MARKER = "# [manual]"

def load_manual_sections(path: Path) -> list[str]:
    """Return lines/blocks marked as manual that must survive re-extraction."""
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    manual_blocks, in_block, block = [], False, []
    for line in lines:
        if MANUAL_MARKER in line:
            in_block = True
        if in_block:
            block.append(line)
            if line.strip() == "" and block:
                manual_blocks.append("\n".join(block))
                block, in_block = [], False
    if block:
        manual_blocks.append("\n".join(block))
    return manual_blocks


# ─────────────────────────────────────────────────────────────────────────────
# Writers
# ─────────────────────────────────────────────────────────────────────────────

def write_tokens(path: Path, colors: Counter, state: dict,
                 spacing, typo, shadows, radii, css_vars, animations,
                 merge: bool):
    manual = load_manual_sections(path) if merge else []

    # Sort colors by accumulated count (cross-run confidence)
    acc_counts = state.get("color_counts", {})
    sorted_colors = sorted(colors.keys(), key=lambda c: -acc_counts.get(c, colors[c]))

    lines = [
        "# Design Tokens — auto-gerado. Re-gere com: python3 extract_design_system.py",
        f"# Runs: {state['runs']}  |  Última extração: {state.get('last_run', 'N/A')}",
        "",
    ]

    if css_vars:
        lines += ["css_variables:"]
        for k, v in list(css_vars.items())[:30]:
            lines.append(f"  {k}: \"{v}\"")
        lines.append("")

    lines += ["colors:  # ordenadas por frequência acumulada entre runs"]
    for c in sorted_colors[:24]:
        count = acc_counts.get(c, colors[c])
        lines.append(f"  - \"{c}\"  # {count} ocorrências")
    lines.append("")

    if typo["families"]:
        lines += ["typography:", "  font_families:"]
        for f in typo["families"]:
            lines.append(f"    - \"{f}\"")
    if typo["sizes"]:
        lines += ["  font_sizes:"]
        for s in typo["sizes"][:8]:
            lines.append(f"    - {s}")
    if typo["weights"]:
        lines += ["  font_weights:"]
        for w in typo["weights"]:
            lines.append(f"    - {w}")
    lines.append("")

    if spacing:
        lines += [f"spacing:  # grade de 4px | {len(spacing)} valores detectados",
                  "  scale: [" + ", ".join(str(s) for s in spacing[:14]) + "]"]
        lines.append("")

    if radii:
        lines += ["border_radius:"]
        for r in radii[:6]:
            lines.append(f"  - {r}")
        lines.append("")

    if shadows:
        lines += ["shadows:"]
        for i, s in enumerate(shadows, 1):
            lines.append(f"  s{i}: \"{s}\"")
        lines.append("")

    if animations:
        lines += ["animations:"]
        for name in list(animations.keys())[:10]:
            lines.append(f"  - {name}")
        lines.append("")

    if manual:
        lines += ["", "# ── Adições manuais (preservadas entre runs) ──"]
        lines += manual

    path.write_text("\n".join(lines))


def write_catalog(path: Path, html_components: dict, js_components: list,
                  class_system: dict, state: dict, merge: bool):
    manual = load_manual_sections(path) if merge else []
    acc = state.get("component_counts", {})

    lines = [
        "# Component Catalog — auto-gerado",
        f"# Para adicionar componente manualmente: adicione '# [manual]' na linha acima do bloco",
        "",
        "## Componentes detectados no HTML",
    ]

    if not html_components:
        lines.append("_Nenhum detectado via classes HTML._")
    else:
        for comp, nodes in sorted(html_components.items()):
            lines += [f"\n### {comp.title()} ({len(nodes)} instância(s))"]
            # show first instance, collapsed
            tag = nodes[0]
            html_str = str(tag)
            if len(html_str) > 600:
                html_str = html_str[:600] + "\n..."
            lines += ["```html", html_str, "```"]

    lines += ["", "---", "", "## Componentes React detectados no bundle"]
    sorted_js = sorted(js_components, key=lambda c: -acc.get(c, 0))
    if not sorted_js:
        lines.append("_Nenhum detectado._")
    else:
        for comp in sorted_js[:50]:
            confidence = "★★★" if acc.get(comp, 0) > 2 else ("★★" if acc.get(comp, 0) > 0 else "★")
            lines.append(f"- `{comp}` {confidence}")

    if class_system["top_prefixes"]:
        lines += ["", "---", "", "## Convenção de CSS classes"]
        lines.append(f"Prefixos detectados: `{'`, `'.join(class_system['top_prefixes'])}`")
        lines.append("")
        lines.append("Classes mais usadas:")
        for cls in class_system["top_classes"][:15]:
            lines.append(f"- `.{cls}`")

    if manual:
        lines += ["", "---", "", "## Adições manuais"]
        lines += manual

    path.write_text("\n".join(lines))


def write_layouts(path: Path, layouts: list, merge: bool):
    manual = load_manual_sections(path) if merge else []

    lines = ["# Layout Patterns — auto-gerado", ""]

    if not layouts:
        lines.append("_Nenhum padrão detectado automaticamente._")
    else:
        for i, lay in enumerate(layouts, 1):
            conf = lay.get("confidence", "?")
            lines += [f"## {i}. {lay['name']}  [{conf}]", ""]

    if manual:
        lines += ["", "---", "## Padrões manuais", ""]
        lines += manual

    path.write_text("\n".join(lines))


def write_agent_context(path: Path, fmt: str, components: list,
                        layouts: list, recipes: dict, state: dict):
    acc = state.get("component_counts", {})
    top_comps = sorted(components, key=lambda c: -acc.get(c, 0))[:20]

    lines = [
        "# AGENT CONTEXT — Guia de navegação do design system",
        f"# Prototype: {fmt} | Run #{state['runs']} | {state.get('last_run', 'N/A')}",
        "",
        "Este arquivo é o ponto de entrada. Leia-o primeiro.",
        "Ele diz ONDE buscar cada tipo de informação e QUANDO usar cada arquivo.",
        "",
        "---",
        "",
        "## Mapa de arquivos — onde procurar o quê",
        "",
        "| Pergunta | Arquivo | Seção |",
        "|----------|---------|-------|",
        "| Qual cor usar para fundo/texto/status? | `design-tokens.yaml` | `colors` |",
        "| Qual espaçamento/padding usar? | `design-tokens.yaml` | `spacing` |",
        "| Qual fonte, tamanho, peso? | `design-tokens.yaml` | `typography` |",
        "| Que sombra ou border-radius usar? | `design-tokens.yaml` | `shadows` / `border_radius` |",
        "| Como montar o botão/modal/card/badge? | `component-catalog.md` | nome do componente |",
        "| Como estruturar o layout da página? | `layout-patterns.md` | padrão mais próximo |",
        "| Quais componentes esta tela usa? | `screen-recipes.md` | nome da tela |",
        "| Esta tela segue o shell padrão? | `compliance-report.md` | — |",
        "",
        "---",
        "",
        "## Regras (sempre aplicar, sem exceção)",
        "",
        "1. **Cores**: apenas de `design-tokens.yaml > colors`. Nunca inventar.",
        "2. **Espaçamento**: múltiplos de 4px. Escala em `design-tokens.yaml > spacing`.",
        "3. **Componentes**: reusar de `component-catalog.md`. Não criar padrões novos.",
        "4. **Layout**: toda tela nova deve seguir um padrão de `layout-patterns.md`.",
        "5. **Composição**: para entender o que uma tela monta, consultar `screen-recipes.md`.",
        "",
        "---",
        "",
        "## Fluxo para gerar uma nova tela",
        "",
        "```",
        "1. Identificar o layout → layout-patterns.md",
        "2. Listar componentes necessários → component-catalog.md",
        "3. Ver tela similar já existente → screen-recipes.md",
        "4. Aplicar cores e espaçamento → design-tokens.yaml",
        "5. Verificar conformidade → compliance-report.md",
        "```",
        "",
        "---",
        "",
        "## Telas existentes no prototype",
        "",
    ]

    if recipes:
        for page in sorted(recipes.keys()):
            children = recipes[page][:5]
            more = len(recipes[page]) - 5
            suffix = f" +{more}" if more > 0 else ""
            lines.append(f"- **{page}**: {', '.join(f'`{c}`' for c in children)}{suffix}")
    else:
        lines.append("_Nenhuma tela mapeada._")

    lines += [
        "",
        "---",
        "",
        "## Componentes disponíveis (por frequência de uso)",
        "",
    ]
    for c in top_comps:
        lines.append(f"- `{c}`")

    lines += [
        "",
        "---",
        "",
        "## Template de prompt para nova tela",
        "",
        "```",
        "Contexto: leia agent-context/AGENT_CONTEXT.md",
        "",
        "Gere a tela [NOME] com:",
        "- Layout: [padrão de layout-patterns.md]",
        "- Tela similar para referência: [nome de screen-recipes.md]",
        "- Componentes: [lista de component-catalog.md]",
        "- Conteúdo: [dados e ações da tela]",
        "```",
    ]

    path.write_text("\n".join(lines))


def write_screen_recipes(path: Path, recipes: dict, merge: bool):
    manual = load_manual_sections(path) if merge else []
    lines = [
        "# Screen Recipes — como montar cada tela",
        "# Auto-gerado a partir da árvore de composição do bundle.",
        "# Este arquivo responde: 'quais componentes esta tela usa e em que ordem?'",
        "",
    ]

    if not recipes:
        lines.append("_Nenhuma receita detectada automaticamente._")
    else:
        for page, children in sorted(recipes.items()):
            lines += [f"## {page}", ""]
            lines.append("```")
            lines.append(f"{page}")
            for child in children:
                lines.append(f"  └── {child}")
            lines.append("```")
            lines.append("")

    if manual:
        lines += ["---", "## Receitas manuais", ""]
        lines += manual

    path.write_text("\n".join(lines))
    print(f"  ✓ screen-recipes.md")


def write_compliance_report(path: Path, violations: list, recipes: dict):
    lines = [
        "# Compliance Report — telas fora do shell padrão",
        "# Telas que não usam nenhum wrapper de layout detectado.",
        "# Use como checklist de migração.",
        "",
        f"Total de telas mapeadas: {len(recipes)}",
        f"Fora do shell: {len(violations)}",
        "",
    ]

    if not violations:
        lines.append("Todas as telas seguem o padrão de shell.")
    else:
        lines += ["## Requer migração", ""]
        for v in violations:
            lines.append(f"- **{v['page']}** — monta: {', '.join(v['mounts'][:6])}")

    lines += ["", "## Telas conformes", ""]
    ok = [p for p in recipes if not any(v["page"] == p for v in violations)]
    for p in sorted(ok):
        lines.append(f"- {p}")

    path.write_text("\n".join(lines))
    print(f"  ✓ compliance-report.md")


def write_report(path: Path, prev_state: dict, new_state: dict,
                 new_colors: Counter, new_components: list):
    prev_colors = set(prev_state.get("color_counts", {}).keys())
    curr_colors = set(new_colors.keys())
    added_colors   = curr_colors - prev_colors
    removed_colors = prev_colors - curr_colors

    prev_comps = set(prev_state.get("component_counts", {}).keys())
    curr_comps = set(new_components)
    added_comps   = curr_comps - prev_comps
    removed_comps = prev_comps - curr_comps

    lines = [
        f"# Extraction Report — {new_state.get('last_run', '')}",
        f"Run #{new_state['runs']}",
        "",
        f"## Cores",
        f"- Total: {len(curr_colors)}",
        f"- Novas: {len(added_colors)} ({', '.join(list(added_colors)[:6]) or 'nenhuma'})",
        f"- Removidas: {len(removed_colors)} ({', '.join(list(removed_colors)[:6]) or 'nenhuma'})",
        "",
        f"## Componentes",
        f"- Total: {len(curr_comps)}",
        f"- Novos: {len(added_comps)} ({', '.join(list(added_comps)[:8]) or 'nenhum'})",
        f"- Removidos: {len(removed_comps)} ({', '.join(list(removed_comps)[:8]) or 'nenhum'})",
    ]

    path.write_text("\n".join(lines))
    print(f"  ✓ {path}")


# ─────────────────────────────────────────────────────────────────────────────
# Main extraction pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run_extraction(html_path: Path, out_dir: Path, merge: bool, state_path: Path) -> dict:
    html_text = html_path.read_text(encoding="utf-8", errors="replace")
    html_hash = hashlib.md5(html_text.encode()).hexdigest()

    state = load_state(state_path)
    prev_state = json.loads(json.dumps(state))  # deep copy for report

    if state.get("html_hash") == html_hash and state.get("runs", 0) > 0:
        print("  Arquivo não mudou desde o último run. Pulando.")
        return state

    soup = BeautifulSoup(html_text, "html.parser")
    fmt  = detect_format(html_text, soup)
    print(f"  Formato detectado: {fmt}")

    sources = get_sources(html_text, soup, fmt)
    print(f"  CSS: {len(sources['css']):,} chars | JS: {len(sources['js']):,} chars")

    colors     = extract_colors(sources)
    spacing    = extract_spacing(sources)
    typo       = extract_typography(sources)
    shadows    = extract_shadows(sources)
    radii      = extract_radii(sources)
    css_vars   = extract_css_vars(sources)
    animations = extract_animations(sources)

    inner_soup      = BeautifulSoup(sources["inner_html"], "html.parser")
    html_components = extract_components_from_html(inner_soup)
    js_components   = extract_components_from_js(sources)
    class_system    = extract_classname_system(sources)
    layouts         = detect_layouts(soup, sources)
    recipes         = extract_composition(sources)
    violations      = detect_shell_violations(recipes)

    print(f"  Cores: {len(colors)} | React: {len(js_components)} | Telas: {len(recipes)} | Violações: {len(violations)}")

    state = accumulate_state(state, colors, js_components)
    state["html_hash"] = html_hash

    out_dir.mkdir(parents=True, exist_ok=True)
    write_tokens(out_dir/"design-tokens.yaml", colors, state, spacing, typo,
                 shadows, radii, css_vars, animations, merge)
    print(f"  ✓ design-tokens.yaml")

    write_catalog(out_dir/"component-catalog.md", html_components, js_components,
                  class_system, state, merge)
    print(f"  ✓ component-catalog.md")

    write_layouts(out_dir/"layout-patterns.md", layouts, merge)
    print(f"  ✓ layout-patterns.md")

    write_screen_recipes(out_dir/"screen-recipes.md", recipes, merge)

    write_compliance_report(out_dir/"compliance-report.md", violations, recipes)

    all_components = js_components + list(html_components.keys())
    write_agent_context(out_dir/"AGENT_CONTEXT.md", fmt, all_components, layouts, recipes, state)
    print(f"  ✓ AGENT_CONTEXT.md")

    write_report(out_dir/"extraction-report.md", prev_state, state, colors, js_components)

    save_state(state_path, state)
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Watch mode
# ─────────────────────────────────────────────────────────────────────────────

def watch_mode(html_path: Path, out_dir: Path, merge: bool, state_path: Path):
    print(f"Watching {html_path} for changes... (Ctrl+C to stop)\n")
    last_hash = ""

    while True:
        try:
            text = html_path.read_text(encoding="utf-8", errors="replace")
            current_hash = hashlib.md5(text.encode()).hexdigest()
            if current_hash != last_hash:
                last_hash = current_hash
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Mudança detectada — extraindo...")
                run_extraction(html_path, out_dir, merge, state_path)
                print("Aguardando próxima mudança...\n")
            time.sleep(2)
        except KeyboardInterrupt:
            print("\nWatch encerrado.")
            break


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    html_path  = Path(args[0])
    watch      = "--watch" in args
    merge      = "--merge" in args

    # Output dir: next non-flag arg or sibling folder
    out_dir = None
    for a in args[1:]:
        if not a.startswith("--"):
            out_dir = Path(a)
            break
    if out_dir is None:
        out_dir = html_path.parent / "agent-context"

    state_path = out_dir / ".extraction-state.json"

    if not html_path.exists():
        print(f"Erro: arquivo não encontrado: {html_path}")
        sys.exit(1)

    print(f"\nPrototype : {html_path}")
    print(f"Output    : {out_dir}")
    print(f"Merge mode: {'sim (edições manuais preservadas)' if merge else 'não'}")
    print(f"Watch mode: {'sim' if watch else 'não'}\n")

    if watch:
        watch_mode(html_path, out_dir, merge, state_path)
    else:
        run_extraction(html_path, out_dir, merge, state_path)
        state = load_state(state_path)
        print(f"\nExtração #run{state['runs']} concluída → {out_dir}/")


if __name__ == "__main__":
    main()
