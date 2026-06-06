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


# ── React/JSX component names ────────────────────────────────────────────────

RE_COMP_FN = re.compile(r'function ([A-Z][a-zA-Z]{2,})\s*\(')

RE_SCREEN_FN = re.compile(
    r'function ([A-Z][a-zA-Z]{2,}'
    r'(?:Page|Screen|Dashboard|Detail|Panel|View|Tab|Section|List|Form|Modal))\s*\('
)

# Matches PascalCase names that look like screen identifiers
RE_SCREEN_NAME = re.compile(
    r'^[A-Z][a-zA-Z]+'
    r'(?:Page|Screen|Dashboard|Detail|Panel|View|Tab|Section|List|Form|Modal)$'
)

RE_JSX_TAG = re.compile(r'<([A-Z][a-zA-Z]{2,})[\s/>]')

RE_JSX_CALL = re.compile(r'jsxs?\(([A-Z][a-zA-Z]{2,})\s*,')

RE_COMP_REF = re.compile(
    r'\b([A-Z][a-zA-Z]{2,}'
    r'(?:Card|Modal|Row|Tab|Panel|Form|Head|List|Table|Btn|Button|Badge|Item|'
    r'Section|Chart|Detail|View|Drawer|Widget|Dot|Pill|Select|Input|Toggle|'
    r'Switch|Avatar|Icon|Spinner|Toast|Alert|Banner))\b'
)


# ── Inline styles ─────────────────────────────────────────────────────────────

RE_INLINE_STYLE = re.compile(r'style=\{\{([^}]{5,600})\}\}')
RE_STYLE_PROP   = re.compile(r'(\w+)\s*:\s*["\']?([^,"\'}\n]{1,60})["\']?')


# ── Interactions ──────────────────────────────────────────────────────────────

RE_MOUSE_ENTER = re.compile(
    r'onMouseEnter[^;]{0,60}style\.(\w+)\s*=\s*["\']([^"\']+)["\']'
)
RE_MOUSE_LEAVE = re.compile(
    r'onMouseLeave[^;]{0,60}style\.(\w+)\s*=\s*["\']([^"\']+)["\']'
)
RE_ON_FOCUS    = re.compile(
    r'onFocus[^;]{0,40}style\.(\w+)\s*=\s*["\']([^"\']+)["\']'
)


# ── CSS class names ───────────────────────────────────────────────────────────

RE_CLASS_NAME = re.compile(r'className\s*[=:]\s*["\']([^"\']{2,120})["\']')


# ── UI text extraction ────────────────────────────────────────────────────────

RE_UI_STRING  = re.compile(r'["\']([A-ZÁÉÍÓÚÀÂÊÎÔÛÃÕÇ][^"\']{2,80})["\']')
RE_PLACEHOLDER = re.compile(r'placeholder[=:]\s*["\']([^"\']{3,60})["\']')
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


# ── Format detection ──────────────────────────────────────────────────────────

RE_TAILWIND_CLASS = re.compile(
    r'\.(flex|grid|p-\d|m-\d|text-[a-z]|bg-[a-z]|border-[a-z])[a-z0-9-]*\s*\{'
)
RE_COMPRESSED_BUNDLE = re.compile(r'"compressed"\s*:\s*true')


# ── Chunk ID generation ───────────────────────────────────────────────────────

RE_CHUNK_ID_INVALID = re.compile(r'[^a-z0-9]+')
