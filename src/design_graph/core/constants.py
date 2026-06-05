"""
Shared constants: React internals to exclude, color semantic labels,
and semantic keyword mappings for HTML component detection.
"""

# React/JS built-in names that should never be treated as user components
REACT_INTERNALS: frozenset[str] = frozenset({
    "Fragment", "Suspense", "StrictMode", "Provider", "Router", "Switch",
    "Route", "Redirect", "ErrorBoundary", "Component", "PureComponent",
    "React", "useState", "useEffect", "useRef", "useCallback", "useMemo",
    "useContext", "useReducer", "createContext", "forwardRef", "memo",
    "ReactDOM", "FiberNode", "FiberRootNode", "SyntheticBaseEvent",
    "ChildReconciler", "Generator", "AsyncGenerator",
    "ReactDOMRoot", "ReactDOMHydrationRoot",
})

# Minimum name length to consider a PascalCase symbol as a component
MIN_COMPONENT_NAME_LENGTH = 3

# Colors to skip when building the token list (too generic / always present)
SKIP_COLORS: frozenset[str] = frozenset({
    "rgba(0,0,0,0)", "transparent", "#000", "#fff", "#000000", "#ffffff",
})

# Semantic labels for common design-system colors
COLOR_SEMANTIC_LABELS: dict[str, str] = {
    "#1a1a1a": "bg_base",       "#1f1f1f": "bg_deep",
    "#2a2a2a": "bg_surface",    "#2e2e2e": "bg_elevated",
    "#333333": "bg_muted",      "#333":    "bg_muted",
    "#3a3a3a": "border_default","#404040": "bg_canvas",
    "#444444": "bg_neutral",    "#444":    "bg_neutral",
    "#ffb81c": "primary",       "#FFB81C": "primary",
    "#f59e0b": "primary_dim",   "#22c55e": "success",
    "#60a5fa": "info",          "#ef4444": "danger",
    "#a78bfa": "premium",       "#9ca3af": "text_muted",
    "#6b7280": "text_disabled", "#ffffff": "white",
    "#fff":    "white",         "#000000": "black",
    "#262626": "bg_darker",     "#1c1c1c": "bg_darkest",
}

# Minimum occurrences for a color to become a design token
MIN_COLOR_OCCURRENCES = 2

# Minimum occurrences for a spacing value to become a design token
MIN_SPACING_OCCURRENCES = 2

# Maximum number of color tokens to store per prototype
MAX_COLOR_TOKENS = 50

# Spacing grid unit (all spacing values are rounded to multiples of this)
SPACING_GRID_PX = 4

# Minimum and maximum spacing values to consider (filter noise)
SPACING_MIN_PX = 2
SPACING_MAX_PX = 200

# ── HTML component detection keywords ────────────────────────────────────────

# Maps semantic component type → CSS class keywords that indicate it
HTML_SEMANTIC_KEYWORDS: dict[str, list[str]] = {
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

# DOM tags excluded from pattern detection — document-level wrappers only.
# NOTE: 'div' and 'span' are intentionally NOT here; they can be components
# when they carry CSS classes (e.g. div.card). The MIN_DOM_SIGNATURE_LENGTH
# filter removes bare <div> and <span> that lack meaningful structure.
LAYOUT_ONLY_TAGS: frozenset[str] = frozenset({
    "html", "head", "body", "script", "style", "link", "meta",
})

# Minimum DOM structure signature length to be considered a component pattern
MIN_DOM_SIGNATURE_LENGTH = 15

# Minimum repetitions for a DOM pattern to be considered a reused component
MIN_DOM_PATTERN_REPETITIONS = 3

# ── Extraction limits (prevent runaway data) ──────────────────────────────────

MAX_STYLES_PER_COMPONENT = 40
MAX_INTERACTIONS_PER_COMPONENT = 15
MAX_TEXTS_PER_COMPONENT = 30
MAX_CLASSES_PER_COMPONENT = 10
MAX_SECTIONS_FROM_STRUCTURAL_FALLBACK = 8
MAX_SECTION_COMMENT_SECTIONS = 20
MAX_TOKENS_IN_SEARCH_QUERY_EXPANSION = 6

# ── JS parser safety limits ───────────────────────────────────────────────────

# Maximum characters to scan beyond a function start when looking for its end
JS_FUNCTION_SCAN_LIMIT = 120_000

# Fallback window size when brace-counting fails
JS_FUNCTION_FALLBACK_WINDOW = 20_000

# ── Chunking ──────────────────────────────────────────────────────────────────

DEFAULT_CHUNK_MAX_CHARS = 12_000

# Estimated tokens = chars / this divisor (conservative estimate)
CHUNK_CHARS_PER_TOKEN = 4
