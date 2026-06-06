"""
Extract design tokens (colors, spacing) from CSS + JS source text.

All sub-functions operate on combined text (css + js) and return
lists of DesignToken instances. No file I/O or graph access here.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter, defaultdict

from design_graph.core.constants import (
    COLOR_SEMANTIC_LABELS,
    FONT_SIZE_MAX_PX,
    FONT_SIZE_MIN_PX,
    FONT_SIZE_SEMANTIC_LABELS,
    FONT_WEIGHT_SEMANTIC_LABELS,
    MAX_COLOR_TOKENS,
    MAX_CSS_VAR_TOKENS,
    MAX_FONT_SIZE_TOKENS,
    MAX_FONT_WEIGHT_TOKENS,
    MAX_RADIUS_TOKENS,
    MAX_SHADOW_TOKENS,
    MIN_COLOR_OCCURRENCES,
    MIN_CSS_VAR_OCCURRENCES,
    MIN_RADIUS_OCCURRENCES,
    MIN_SHADOW_OCCURRENCES,
    MIN_SPACING_OCCURRENCES,
    MIN_TYPOGRAPHY_OCCURRENCES,
    SKIP_COLORS,
    SPACING_GRID_PX,
    SPACING_MAX_PX,
    SPACING_MIN_PX,
)
from design_graph.core.models import DesignToken, RawSources
from design_graph.core.patterns import (
    RE_BORDER_RADIUS,
    RE_BOX_SHADOW,
    RE_COLOR,
    RE_CSS_VAR,
    RE_FONT_SIZE,
    RE_FONT_WEIGHT,
    RE_PX_VALUE,
    RE_SPACING,
)

logger = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────────────

def extract_tokens(sources: RawSources) -> list[DesignToken]:
    """
    Extract all design tokens from sources.css + sources.js combined.
    Returns a list sorted by category ascending, then usage descending.
    """
    combined = sources.css + "\n" + sources.js

    colors     = _extract_colors(combined)
    spacing    = _extract_spacing(combined)
    typography = _extract_typography(combined)
    shadows    = _extract_shadows(combined)

    radii      = _extract_radii(combined)
    css_vars   = _extract_css_vars(combined)
    all_tokens = colors + spacing + typography + shadows + radii + css_vars
    all_tokens.sort(key=lambda t: (t.category, -t.usage))

    logger.debug(
        "extract_tokens: %d color, %d spacing, %d typography, %d shadow, %d radius, %d css_var",
        len(colors), len(spacing), len(typography), len(shadows), len(radii), len(css_vars),
    )
    return all_tokens


def build_token_map(tokens: list[DesignToken]) -> dict[str, list[DesignToken]]:
    """
    Build a lookup index: value.lower() → [DesignToken, ...].
    Used by ComponentExtractor to link inline style values to tokens.
    """
    index: dict[str, list[DesignToken]] = defaultdict(list)
    for token in tokens:
        index[token.value.lower()].append(token)
    return dict(index)


# ── Color extraction ──────────────────────────────────────────────────────────

def _normalise_color(raw: str) -> str:
    """Normalise hex colors to lowercase 6-digit form; leave rgba/hsla as-is."""
    c = raw.strip().lower().replace(" ", "")
    if re.match(r"^#[0-9a-f]{3}$", c):
        # #abc → #aabbcc
        c = "#" + "".join(ch * 2 for ch in c[1:])
    return c


def _color_label(color: str) -> str:
    """Return a semantic label for known colors, or the hex value itself."""
    return COLOR_SEMANTIC_LABELS.get(color, COLOR_SEMANTIC_LABELS.get(color.upper(), color))


def _token_id(value: str, prefix: str) -> str:
    digest = hashlib.md5(value.encode()).hexdigest()[:8]
    return f"{prefix}{digest}"


def _extract_colors(combined: str) -> list[DesignToken]:
    raw_counts: Counter[str] = Counter(
        _normalise_color(m) for m in RE_COLOR.findall(combined)
    )

    tokens: list[DesignToken] = []
    seen_ids: set[str] = set()

    for color, count in raw_counts.most_common(MAX_COLOR_TOKENS * 2):
        if color in SKIP_COLORS:
            continue
        if count < MIN_COLOR_OCCURRENCES:
            continue

        tid = _token_id(color, "col_")
        if tid in seen_ids:
            continue
        seen_ids.add(tid)

        tokens.append(DesignToken(
            id=tid,
            category="color",
            label=_color_label(color),
            value=color,
            usage=count,
        ))

        if len(tokens) >= MAX_COLOR_TOKENS:
            break

    return tokens


# ── Spacing extraction ────────────────────────────────────────────────────────

def _normalise_spacing_to_grid(px_value: int) -> int:
    """Round a pixel value to the nearest multiple of SPACING_GRID_PX."""
    return round(px_value / SPACING_GRID_PX) * SPACING_GRID_PX


def _extract_spacing(combined: str) -> list[DesignToken]:
    raw_values: list[int] = []

    for spacing_match in RE_SPACING.finditer(combined):
        for px_match in RE_PX_VALUE.finditer(spacing_match.group(1)):
            value_str, unit = px_match.groups()
            if unit == "px":
                try:
                    raw_values.append(int(float(value_str)))
                except ValueError:
                    pass

    raw_counts: Counter[int] = Counter(raw_values)

    # Normalise to grid and aggregate counts
    grid_counts: Counter[int] = Counter()
    for raw_px, count in raw_counts.items():
        if SPACING_MIN_PX < raw_px < SPACING_MAX_PX:
            grid_counts[_normalise_spacing_to_grid(raw_px)] += count

    tokens: list[DesignToken] = []
    for grid_px, count in grid_counts.most_common():
        if count < MIN_SPACING_OCCURRENCES:
            continue
        tid = f"sp_{grid_px}"
        tokens.append(DesignToken(
            id=tid,
            category="spacing",
            label=f"space_{grid_px}",
            value=f"{grid_px}px",
            usage=count,
        ))

    return tokens


# ── Typography extraction ─────────────────────────────────────────────────────

def _typography_size_label(px: int) -> str:
    """Return a semantic label for a font-size pixel value."""
    if px in FONT_SIZE_SEMANTIC_LABELS:
        return FONT_SIZE_SEMANTIC_LABELS[px]
    # Nearest match by sorted distance
    nearest = min(FONT_SIZE_SEMANTIC_LABELS.keys(), key=lambda k: abs(k - px))
    return FONT_SIZE_SEMANTIC_LABELS[nearest]


def _extract_font_sizes(combined: str) -> list[DesignToken]:
    """Extract font-size values and map them to typography tokens."""
    raw_px_counts: Counter[int] = Counter()

    for size_match in RE_FONT_SIZE.finditer(combined):
        for px_match in RE_PX_VALUE.finditer(size_match.group(1)):
            value_str, unit = px_match.groups()
            if unit == "px":
                try:
                    px = int(float(value_str))
                    if FONT_SIZE_MIN_PX <= px <= FONT_SIZE_MAX_PX:
                        raw_px_counts[px] += 1
                except ValueError:
                    pass

    tokens: list[DesignToken] = []
    for px, count in raw_px_counts.most_common(MAX_FONT_SIZE_TOKENS):
        if count < MIN_TYPOGRAPHY_OCCURRENCES:
            continue
        tid = f"fs_{px}"
        tokens.append(DesignToken(
            id=tid,
            category="typography",
            label=_typography_size_label(px),
            value=f"{px}px",
            usage=count,
        ))

    return tokens


def _extract_font_weights(combined: str) -> list[DesignToken]:
    """Extract font-weight values and map them to typography tokens."""
    raw_counts: Counter[str] = Counter(
        m.strip().lower() for m in RE_FONT_WEIGHT.findall(combined)
    )

    tokens: list[DesignToken] = []
    for raw_weight, count in raw_counts.most_common(MAX_FONT_WEIGHT_TOKENS):
        if count < MIN_TYPOGRAPHY_OCCURRENCES:
            continue
        label = FONT_WEIGHT_SEMANTIC_LABELS.get(raw_weight, f"weight_{raw_weight}")
        tid   = _token_id(raw_weight, "fw_")
        tokens.append(DesignToken(
            id=tid,
            category="typography",
            label=label,
            value=raw_weight,
            usage=count,
        ))

    return tokens


def _extract_typography(combined: str) -> list[DesignToken]:
    """Combine font-size and font-weight tokens into the typography category."""
    return _extract_font_sizes(combined) + _extract_font_weights(combined)


# ── Shadow extraction ─────────────────────────────────────────────────────────

def _normalise_shadow(raw: str) -> str:
    """Collapse extra whitespace and lower-case a shadow value for deduplication."""
    return " ".join(raw.strip().lower().split())


def _extract_shadows(combined: str) -> list[DesignToken]:
    """Extract unique box-shadow values and rank them by occurrence frequency."""
    raw_counts: Counter[str] = Counter(
        _normalise_shadow(m) for m in RE_BOX_SHADOW.findall(combined)
    )

    tokens: list[DesignToken] = []
    rank = 1
    for shadow_value, count in raw_counts.most_common(MAX_SHADOW_TOKENS):
        if count < MIN_SHADOW_OCCURRENCES:
            continue
        tid = _token_id(shadow_value, "sh_")
        tokens.append(DesignToken(
            id=tid,
            category="shadow",
            label=f"shadow_{rank}",
            value=shadow_value,
            usage=count,
        ))
        rank += 1

    return tokens


# ── Radius extraction ─────────────────────────────────────────────────────────

def _radius_label(raw_value: str) -> str:
    """
    Map a border-radius value to a semantic label using size ranges.
    Returns "radius_full" for percentage values, otherwise a t-shirt size.
    """
    v = raw_value.strip().lower()
    if "%" in v:
        return "radius_full"
    try:
        px = int(float(v.replace("px", "")))
    except ValueError:
        return f"radius_{v[:12]}"

    if px <= 4:
        return "radius_xs"
    if px <= 8:
        return "radius_sm"
    if px <= 12:
        return "radius_md"
    if px <= 20:
        return "radius_lg"
    return "radius_xl"


def _normalise_radius(raw: str) -> str:
    """Strip quotes, lowercase, and trim whitespace from a radius value."""
    return raw.strip().strip("'\"").lower()


def _extract_radii(combined: str) -> list[DesignToken]:
    """Extract border-radius values and classify them by size range."""
    raw_counts: Counter[str] = Counter(
        _normalise_radius(m) for m in RE_BORDER_RADIUS.findall(combined)
        if _normalise_radius(m) and re.search(r'[\d%]', _normalise_radius(m))
    )

    tokens: list[DesignToken] = []
    for radius_value, count in raw_counts.most_common(MAX_RADIUS_TOKENS):
        if count < MIN_RADIUS_OCCURRENCES:
            continue
        first_component = radius_value.split()[0]
        tid = _token_id(first_component, "rx_")
        tokens.append(DesignToken(
            id=tid,
            category="radius",
            label=_radius_label(first_component),
            value=first_component,
            usage=count,
        ))

    return tokens


# ── CSS custom-property extraction ────────────────────────────────────────────

def _css_var_label(var_name: str) -> str:
    """Convert a CSS variable name to a snake_case label without leading dashes."""
    # "--primary-color" → "primary_color"
    return var_name.lstrip("-").replace("-", "_")


def _extract_css_vars(combined: str) -> list[DesignToken]:
    """
    Extract CSS custom properties (--name: value) as design tokens.
    Label = variable name in snake_case; value = the declared value (trimmed).
    One occurrence is enough — variables are typically defined once.
    """
    # Each match is a full "--name: value" string
    var_definitions: dict[str, str] = {}
    var_counts: Counter[str] = Counter()

    for match_text in RE_CSS_VAR.findall(combined):
        name_part, _, value_part = match_text.partition(":")
        name  = name_part.strip()
        value = value_part.strip().rstrip(";").strip()
        if not name.startswith("--") or not value:
            continue
        var_definitions[name] = value
        var_counts[name] += 1

    tokens: list[DesignToken] = []
    for var_name, count in var_counts.most_common(MAX_CSS_VAR_TOKENS):
        if count < MIN_CSS_VAR_OCCURRENCES:
            continue
        value = var_definitions[var_name]
        tid   = _token_id(var_name, "cv_")
        tokens.append(DesignToken(
            id=tid,
            category="css_var",
            label=_css_var_label(var_name),
            value=value,
            usage=count,
        ))

    return tokens
