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
    MAX_COLOR_TOKENS,
    MIN_COLOR_OCCURRENCES,
    MIN_SPACING_OCCURRENCES,
    SKIP_COLORS,
    SPACING_GRID_PX,
    SPACING_MAX_PX,
    SPACING_MIN_PX,
)
from design_graph.core.models import DesignToken, RawSources
from design_graph.core.patterns import RE_COLOR, RE_PX_VALUE, RE_SPACING

logger = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────────────

def extract_tokens(sources: RawSources) -> list[DesignToken]:
    """
    Extract all design tokens from sources.css + sources.js combined.
    Returns a list sorted by category ascending, then usage descending.
    """
    combined = sources.css + "\n" + sources.js

    colors  = _extract_colors(combined)
    spacing = _extract_spacing(combined)

    all_tokens = colors + spacing
    all_tokens.sort(key=lambda t: (t.category, -t.usage))

    logger.debug(
        "extract_tokens: %d color tokens, %d spacing tokens",
        len(colors), len(spacing),
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
