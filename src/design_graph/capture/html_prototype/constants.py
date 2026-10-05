"""
Thresholds and limits of the html_prototype capture: React internals to
exclude, token-promotion thresholds and per-component extraction caps.

Color labels are not among these: a hardcoded hex→label table shared
across every prototype this server ever loads would mislabel a color the
instant a prototype's own palette gives that hex a different meaning than
whichever prototype the table was written against (see
parsing.palette_extractor — labels are derived per-prototype instead).
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


# Colors to skip when building the token list (too generic / always present)
SKIP_COLORS: frozenset[str] = frozenset({
    "rgba(0,0,0,0)", "transparent", "#000", "#fff", "#000000", "#ffffff",
})

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
MAX_CLASSES_PER_COMPONENT = 10
MAX_SECTIONS_FROM_STRUCTURAL_FALLBACK = 8

# ── JS parser safety limits ───────────────────────────────────────────────────

# Maximum characters to scan beyond a function start when looking for its end
JS_FUNCTION_SCAN_LIMIT = 120_000

# Fallback window size when brace-counting fails
JS_FUNCTION_FALLBACK_WINDOW = 20_000

# ── Typography tokens ─────────────────────────────────────────────────────────

MIN_TYPOGRAPHY_OCCURRENCES = 2
MAX_FONT_SIZE_TOKENS        = 15
MAX_FONT_WEIGHT_TOKENS      = 8

# Maps pixel font-size (int) to a Tailwind-style semantic label
FONT_SIZE_SEMANTIC_LABELS: dict[int, str] = {
    10: "text_xs",   11: "text_xs",   12: "text_xs",
    13: "text_sm",   14: "text_sm",
    15: "text_base", 16: "text_base",
    17: "text_lg",   18: "text_lg",
    20: "text_xl",   21: "text_xl",
    24: "text_2xl",
    28: "text_3xl",  30: "text_3xl",
    32: "text_4xl",
    36: "text_5xl",
    40: "text_6xl",
    48: "text_7xl",
    60: "text_8xl",  64: "text_8xl",
    72: "text_9xl",
}

# Maps raw font-weight string (numeric or keyword) to a semantic label
FONT_WEIGHT_SEMANTIC_LABELS: dict[str, str] = {
    "100": "weight_thin",
    "200": "weight_extralight",
    "300": "weight_light",
    "400": "weight_normal",
    "500": "weight_medium",
    "600": "weight_semibold",
    "700": "weight_bold",
    "800": "weight_extrabold",
    "900": "weight_black",
    "bold":     "weight_bold",
    "semibold": "weight_semibold",
}

# Font size range accepted as a design token (avoids icon-size noise)
FONT_SIZE_MIN_PX = 8
FONT_SIZE_MAX_PX = 72

# ── Shadow tokens ─────────────────────────────────────────────────────────────

MIN_SHADOW_OCCURRENCES = 2
MAX_SHADOW_TOKENS      = 8

# ── Radius tokens ─────────────────────────────────────────────────────────────

MIN_RADIUS_OCCURRENCES = 2
MAX_RADIUS_TOKENS      = 10

# ── CSS custom-property tokens ────────────────────────────────────────────────

MIN_CSS_VAR_OCCURRENCES = 1   # definitions typically appear once in the source
MAX_CSS_VAR_TOKENS      = 30
