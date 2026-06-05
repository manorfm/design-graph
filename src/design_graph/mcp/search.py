"""
Cross-prototype search with relevance scoring.

Replaces the legacy CONTAINS-only literal search with a scored, alias-aware
search that ranks exact > prefix > suffix > contains matches.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from design_graph.core.constants import MAX_TOKENS_IN_SEARCH_QUERY_EXPANSION
from design_graph.graph.reader import GraphReader
from design_graph.mcp.aliases import get_aliases

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    type: str    # "Screen" | "Component" | "Token" | "UIText"
    name: str
    detail: str
    id: str      # unique identifier within its type
    doc: str     # prototype/document name
    score: int   # 0–100


def score_match(name: str, query: str) -> int:
    """
    Score how well a name matches a query string.

    100 — exact match (case-insensitive)
     80 — prefix match
     60 — suffix match
     40 — substring match
      0 — no match
    """
    if not name or not query:
        return 0
    n, q = name.lower(), query.lower()
    if n == q:
        return 100
    if n.startswith(q):
        return 80
    if n.endswith(q):
        return 60
    if q in n:
        return 40
    return 0


def expand_query(query: str, aliases: dict[str, list[str]]) -> list[str]:
    """
    Return the query plus any alias expansions, deduplicated and capped.
    All terms are lowercased for consistent matching.
    """
    q = query.lower().strip()
    if not q:
        return []

    terms: list[str] = [q]
    for alias_key, expansions in aliases.items():
        if alias_key in q:
            terms.extend(e.lower() for e in expansions)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            unique.append(term)

    return unique[:MAX_TOKENS_IN_SEARCH_QUERY_EXPANSION]


def search(
    readers: list[tuple[str, GraphReader]],
    query: str,
    max_results: int = 30,
) -> list[SearchResult]:
    """
    Search across all loaded prototypes with relevance scoring.

    Results are deduplicated by (doc, id) and sorted by score descending.
    Returns at most max_results items.
    """
    if not query.strip():
        return []

    aliases = get_aliases()
    terms   = expand_query(query, aliases)
    results: list[SearchResult] = []
    seen_keys: set[tuple[str, str]] = set()

    for doc_name, reader in readers:
        for term in terms:
            for result in _search_reader(reader, doc_name, term):
                key = (result.doc, result.id)
                if key not in seen_keys:
                    seen_keys.add(key)
                    results.append(result)

    results.sort(key=lambda r: -r.score)
    logger.debug(
        "search: query=%r terms=%r found=%d", query, terms, len(results)
    )
    return results[:max_results]


# ── Private helpers ───────────────────────────────────────────────────────────

def _search_reader(
    reader: GraphReader, doc_name: str, term: str
) -> list[SearchResult]:
    """Search one reader for one query term."""
    results: list[SearchResult] = []

    for screen in reader.list_screens():
        name = screen["name"]
        s = score_match(name, term)
        if s > 0:
            results.append(SearchResult(
                type="Screen", name=name, detail="", id=name, doc=doc_name, score=s
            ))

    all_screens = {s["name"] for s in reader.list_screens()}
    # Component search via get_component (fuzzy) is expensive; query directly
    # We approximate by listing from screens' component lists
    seen_comps: set[str] = set()
    for screen_dict in reader.list_screens():
        for comp_name in screen_dict.get("top_components", []):
            if comp_name in seen_comps:
                continue
            seen_comps.add(comp_name)
            s = score_match(comp_name, term)
            if s > 0:
                results.append(SearchResult(
                    type="Component", name=comp_name, detail="",
                    id=comp_name, doc=doc_name, score=s,
                ))

    for token in reader.get_tokens():
        label = token.get("t.label", "")
        value = token.get("t.value", "")
        s = max(score_match(label, term), score_match(value, term))
        if s > 0:
            results.append(SearchResult(
                type="Token", name=label, detail=value,
                id=token.get("t.id", label), doc=doc_name, score=s,
            ))

    return results
