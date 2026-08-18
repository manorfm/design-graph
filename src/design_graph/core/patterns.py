"""
All compiled regular expressions for the design-graph system.

Centralised here so that:
- No regex literal appears in business logic modules
- Changes to patterns are isolated and visible
- Tests can import patterns directly without importing heavy modules

Naming convention:
  RE_<WHAT_IT_MATCHES>  — general purpose
  RE_<SCOPE>_<WHAT>     — scoped to a specific module/phase
"""

import re

# ── Color and spacing ─────────────────────────────────────────────────────────

RE_COLOR = re.compile(
    r'#(?:[0-9a-fA-F]{3,4}){1,2}\b'
    r'|rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+(?:\s*,\s*[\d.]+)?\s*\)'
    r'|hsla?\(\s*\d+\s*,\s*[\d.]+%\s*,\s*[\d.]+%(?:\s*,\s*[\d.]+)?\s*\)'
)

RE_SPACING = re.compile(
    r'(?:margin|padding|gap|rowGap|columnGap|marginTop|marginBottom|marginLeft|marginRight'
    r'|paddingTop|paddingBottom|paddingLeft|paddingRight)\s*[=:]\s*["\']?([^;}{"\'\n]{1,30})'
)

RE_PX_VALUE = re.compile(r'\b(\d*\.?\d+)(px|rem|em|%|vh|vw)\b')


# ── Typography ────────────────────────────────────────────────────────────────

RE_FONT_FAMILY = re.compile(r"font-?[Ff]amily\s*[=:]\s*[\"']?([^;}{\"'\n]{5,80})")
RE_FONT_SIZE   = re.compile(r"font-?[Ss]ize\s*[=:]\s*[\"']?([^;}{\"'\n]{2,20})")
RE_FONT_WEIGHT = re.compile(r"font-?[Ww]eight\s*[=:]\s*[\"']?(\d{3,4}|bold|semibold)")


# ── Visual properties ─────────────────────────────────────────────────────────

RE_BOX_SHADOW  = re.compile(r'(?:box-shadow|boxShadow|text-shadow|textShadow)\s*[=:]\s*["\']?([^;}{"\'\n]{10,})')
RE_BORDER_RADIUS = re.compile(r'border-?[Rr]adius\s*[=:]\s*["\']?([^;}{"\'\n]{2,30})')
RE_CSS_VAR     = re.compile(r'--[\w-]+\s*:\s*[^;}{]+')
RE_TRANSITION  = re.compile(r'transition["\']?\s*:\s*["\']?([^,"\'}\n]{5,60})')


# ── React component prop declarations ────────────────────────────────────────

# Matches the destructured props block in a function component signature:
#   function NavBar({ title, items = [], onClose })  →  group(1) = "title, items = [], onClose"
# Handles both `function Name({...})` and `const Name = ({...}) =>` forms.
RE_DESTRUCTURED_PROPS = re.compile(
    r'(?:function\s+[A-Z]\w+|const\s+[A-Z]\w+\s*=)\s*\(\s*\{([^}]{1,600})\}',
    re.DOTALL,
)


# ── React/JSX component names ────────────────────────────────────────────────

RE_COMP_FN = re.compile(r'function ([A-Z][a-zA-Z0-9]{2,})\s*\(')

# Arrow-function component declarations: const OptRow = ({ ... }) => ( <div/> )
# Covers both brace-bodied (=> { return (...) }) and implicit-return (=> (...)) forms —
# js_parser.body_start()/function_end() pick the right delimiter pair per case.
RE_COMP_ARROW_FN = re.compile(r'const ([A-Z][a-zA-Z0-9]{2,})\s*=\s*\(')

# A function is visual only when its return expression creates JSX/HTML.
# Supports source JSX and common compiled jsx/jsxs factory calls, from either
# an explicit `return` statement or an arrow function's implicit `=>` return.
# Uses a lookahead so match.end() lands exactly at the expression start,
# regardless of which keyword (return / =>) triggered the match.
RE_VISUAL_RETURN = re.compile(
    r'(?:return|=>)\s*(?=\(\s*<(?:[A-Za-z]|>)|<(?:[A-Za-z]|>)|(?:[A-Za-z_$][\w$]*\.)?jsx?s?\s*\()',
    re.DOTALL,
)

RE_JSX_TAG = re.compile(r'<([A-Z][a-zA-Z0-9]{2,})[\s/>]')

RE_JSX_CALL = re.compile(r'jsxs?\(([A-Z][a-zA-Z0-9]{2,})\s*,')

RE_COMP_REF = re.compile(
    r'\b([A-Z][a-zA-Z0-9]{2,}'
    r'(?:Card|Modal|Row|Tab|Panel|Form|Head|List|Table|Btn|Button|Badge|Item|'
    r'Section|Chart|Detail|View|Drawer|Widget|Dot|Pill|Select|Input|Toggle|'
    r'Switch|Avatar|Icon|Spinner|Toast|Alert|Banner))\b'
)

# Re-export binding: const Badge = window.V6K.Pill;
# Neither RE_COMP_FN nor RE_COMP_ARROW_FN matches this — there's no `(` after
# `=`, since it assigns an existing component rather than defining a new one.
# Left unresolved, JSX references to the alias name (group 1) would produce
# an empty unresolved-component shell instead of finding the real definition
# (group 2, the member being re-exported).
RE_COMPONENT_ALIAS = re.compile(
    r'\bconst\s+([A-Z][a-zA-Z0-9]{2,})\s*=\s*'
    r'[a-zA-Z_$][\w$]*(?:\.[a-zA-Z_$][\w$]*)*\.([A-Z][a-zA-Z0-9]{2,})\s*;'
)

# ── Inline styles ─────────────────────────────────────────────────────────────

RE_INLINE_STYLE = re.compile(r'style=\{\{([^}]{5,600})\}\}')
RE_STYLE_PROP   = re.compile(r'(\w+)\s*:\s*["\']?([^,"\'}\n]{1,60})["\']?')


# ── Interactions ──────────────────────────────────────────────────────────────

# Imperative hover/focus feedback: onMouseEnter={e => e.currentTarget.style.X = Y}
# Y may be a quoted literal ('#333'), a token/prop reference (C.red, o.color), or
# a small expression (color + '12') — captured as raw text; extract_component
# strips a fully-wrapping quote pair, leaving identifiers/expressions intact.
#
# Applied to a single handler's *isolated* body (see js_parser.find_matching_delimiter
# + re_event_handler_open below) so every `style.prop = value` statement inside a
# multi-statement handler (`e => { style.a = X; style.b = Y; }`) is captured, not
# just the first.
RE_STYLE_MUTATION = re.compile(r'style\.(\w+)\s*=\s*([^;}]{1,80})')


def re_event_handler_open(event: str) -> re.Pattern:
    """
    Match the opening `{` of `<event>={...}` (onMouseEnter, onMouseLeave, onFocus).
    Combine with js_parser.find_matching_delimiter(js, match.end() - 1) to isolate
    the full handler body — including a nested block (`e => { ... }`) — so every
    statement inside can be scanned, not just text up to the first `;`/`}`.
    """
    return re.compile(rf'\b{event}\s*=\s*\{{')


# React boolean state used to toggle style via a ternary instead of an imperative
# style.prop = value mutation:
#   const [hov, setHov] = useState(false);
#   onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
#   style={{ border: `1px solid ${hov ? C.accent : C.border}` }}
RE_USE_STATE_BOOL = re.compile(
    r'const\s*\[\s*(\w+)\s*,\s*(set\w+)\s*\]\s*=\s*useState\(\s*(?:true|false)\s*\)'
)


def re_state_setter_trigger(setter: str, event: str) -> re.Pattern:
    """<event>={...<setter>(true|false)...} — ties a state setter to the DOM
    event that flips it (e.g. onMouseEnter={() => setHov(true)})."""
    return re.compile(rf'\b{event}\b[^}}]{{0,40}}\b{re.escape(setter)}\((?:true|false)\)')


def re_state_ternary_style(state: str) -> re.Pattern:
    """
    `prop: <state> ? A : B`, including when the ternary sits inside a
    template-literal interpolation (`prop: \\`... ${state ? A : B} ...\\``).
    Scoped to a single component's window by the caller — state-var names like
    `hov`/`h` are commonly reused across unrelated sibling components.
    """
    s = re.escape(state)
    return re.compile(
        rf'(\w+)\s*:\s*[^,}}]*?\b{s}\s*\?\s*([^:?]{{1,80}})\s*:\s*([^,;\n}}]{{1,80}})'
    )


# ── CSS class names ───────────────────────────────────────────────────────────

RE_CLASS_NAME = re.compile(r'className\s*[=:]\s*["\']([^"\']{2,120})["\']')


# ── UI text extraction ────────────────────────────────────────────────────────

RE_UI_STRING  = re.compile(r'["\']([A-ZÁÉÍÓÚÀÂÊÎÔÛÃÕÇ][^"\']{2,80})["\']')
RE_PLACEHOLDER = re.compile(r'placeholder[=:]\s*["\']([^"\']{3,60})["\']')
RE_TOOLTIP_TEXT = re.compile(r'(?:title|aria-label|alt)\s*=\s*["\']([^"\']{3,80})["\']')
RE_HEADING     = re.compile(r'<h[1-6][^>]*>\s*["\']?([^<"\']{3,60})')
RE_BUTTON_TEXT = re.compile(r'<(?:button|Btn)[\s\S]*?>\s*\n?\s*([A-ZÁÉÍÓÚÀÂÊÎÔÛÃÕÇ][^<"\']{1,39})')
RE_LABEL_TEXT  = re.compile(r'<(?:label|span)[^>]*>\s*["\']?([^<"\']{3,60})')


# ── JSX section comments ──────────────────────────────────────────────────────

RE_SECTION_COMMENT = re.compile(
    r'\{/\*\s*[─━\-=*]{0,6}\s*(.{2,40}?)\s*[─━\-=*]{0,6}\s*\*/\}'
)


# ── JSX sanitization ─────────────────────────────────────────────────────────

RE_LONG_EVENT_HANDLER = re.compile(
    r'on[A-Z]\w+\s*=\s*\{(?:[^{}]|\{[^{}]*\}){60,}\}'
)
RE_LONG_ARROW_FN = re.compile(
    r'\.\w+\s*\(\s*(?:\([^)]*\)|[\w,\s]+)\s*=>\s*\{[^}]{120,}\}'
)
RE_LONG_TERNARY = re.compile(r'\{[^{}]{300,}\}')

# JSX typed marker patterns — used by jsx_sanitizer.sanitize_jsx to replace
# dynamic expressions with structured markers instead of erasing them.
#
# Each pattern below matches only the *head* of the expression — up to the
# opening `<Component` tag — never its end. The true end is found by scanning
# forward from the leading `{` for its balanced closing `}`
# (parsing.js_parser.find_matching_delimiter), not by a regex tail such as
# `[^}]{0,400}\}`. A tail like that stops at the FIRST `}` it meets, and a
# component prop as ordinary as `color={C.red}` supplies one well before the
# expression's real end — corrupting the match and leaking raw JSX into the
# replacement. Balanced scanning has no such failure mode.

# {items.map(item => <Component ... />)}  or  {items.map((item) => <Component/>)}
RE_JSX_LIST_HEAD = re.compile(
    r'\{[^{}<>]{0,80}\.map\([^)]{0,120}\s*=>\s*(?:\([^)]*\)|\s*)?<([A-Z][A-Za-z0-9]+)',
    re.DOTALL,
)

# {condition && <Component ... />}
# Note: avoid && inside [] to prevent FutureWarning (set intersection) in Python 3.12+
RE_JSX_CONDITIONAL_HEAD = re.compile(
    r'\{[^{}<>&]{1,120}&{2}\s*<([A-Z][A-Za-z0-9]+)',
    re.DOTALL,
)

# {condition ? <ComponentA ... /> : <ComponentB ... />} — then-branch name only.
# The else-branch name is read from the already balance-bounded region text
# via RE_JSX_EITHER_ELSE_BRANCH, never by regex-scanning an unbounded tail.
RE_JSX_EITHER_HEAD = re.compile(
    r'\{[^{}<>?]{1,120}\?\s*<([A-Z][A-Za-z0-9]+)',
    re.DOTALL,
)
RE_JSX_EITHER_ELSE_BRANCH = re.compile(r':\s*<([A-Z][A-Za-z0-9]+)')

# {condition && <span>...</span>}  or  {condition && (<svg>...</svg>)}
# Raw markup — an icon, a decorative wrapper — with no PascalCase component
# name, conditionally rendered. Never collapsed into a marker: unlike a named
# component (whose real shape is one get_component_spec call away), this is
# the ONLY copy of that markup's visual detail. These patterns exist purely
# to locate and protect such spans from the generic long-expression fallback
# below, so whether one survives sanitization stops depending on how many
# characters it happens to be.
RE_JSX_MARKUP_CONDITIONAL_HEAD = re.compile(
    r'\{[^{}<>&]{1,120}&{2}\s*\(?\s*<[a-z][a-zA-Z0-9]*',
    re.DOTALL,
)
RE_JSX_MARKUP_EITHER_HEAD = re.compile(
    r'\{[^{}<>?]{1,120}\?\s*\(?\s*<[a-z][a-zA-Z0-9]*',
    re.DOTALL,
)

# Extracts PascalCase component names from typed markers  {[conditional:X]} etc.
RE_JSX_MARKER_COMP = re.compile(
    r'\[\s*(?:conditional|list|either)\s*:\s*([A-Z][A-Za-z0-9]*(?:\|[A-Z][A-Za-z0-9]*)*)\s*\]'
)

# ── Icon markup ────────────────────────────────────────────────────────────────
# extraction.icon_extractor scans a component's raw jsx for <svg>...</svg> (or
# self-closing <svg .../>) blocks and replaces each with a {[icon:id]} marker,
# deduplicating identical icon markup across the graph. Nested <svg> tags are
# matched by depth, not just the first </svg> found, so an icon that legally
# nests another <svg> inside it (e.g. a <use>/<symbol> sprite defs block) still
# resolves to its true closing tag rather than the innermost one.
RE_SVG_OPEN_TAG  = re.compile(r'<svg\b[^>]*?(?P<self_close>/)?>', re.IGNORECASE)
RE_SVG_CLOSE_TAG = re.compile(r'</svg\s*>', re.IGNORECASE)

# Matches the {[icon:id]} marker IconAsset.__str__ produces, for expansion
# back into full markup by graph.reader.GraphReader._resolve_icons.
RE_ICON_MARKER = re.compile(r'\{\[icon:(icon_[0-9a-f]{8})\]\}')


# ── Format detection ──────────────────────────────────────────────────────────

RE_TAILWIND_CLASS = re.compile(
    r'\.(flex|grid|p-\d|m-\d|text-[a-z]|bg-[a-z]|border-[a-z])[a-z0-9-]*\s*\{'
)
RE_COMPRESSED_BUNDLE = re.compile(r'"compressed"\s*:\s*true')


# ── Chunk ID generation ───────────────────────────────────────────────────────

RE_CHUNK_ID_INVALID = re.compile(r'[^a-z0-9]+')
