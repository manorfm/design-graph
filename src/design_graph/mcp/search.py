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
    Return the query's words plus the whole phrase and any alias
    expansions, deduplicated and capped. All terms are lowercased for
    consistent matching.

    Component/screen names are single PascalCase tokens, so a multi-word
    query only ever matches one by one of its words — the whole phrase is
    kept too because UIText content (real sentences) can match it whole.
    No regex is compiled from `query` anywhere in this module: an MCP
    search query is external input, and a regex built from it would be a
    ReDoS vector.
    """
    q = query.lower().strip()
    if not q:
        return []

    terms: list[str] = [q, *q.split()]
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

    A result found by more than one term (e.g. two different query words
    both matching the same component) keeps its best score, not whichever
    term happened to run first. Ranked by how many distinct query words
    the result covers, then by that best score — a name matching every
    word in the query outranks one matching only one, even at equal score.
    Deduplicated by (doc, id). Returns at most max_results items.
    """
    if not query.strip():
        return []

    aliases      = get_aliases()
    terms        = expand_query(query, aliases)
    query_words  = set(query.lower().split())
    best_by_key: dict[tuple[str, str], SearchResult] = {}

    for doc_name, reader in readers:
        for term in terms:
            for result in _search_reader(reader, doc_name, term):
                key = (result.doc, result.id)
                current_best = best_by_key.get(key)
                if current_best is None or result.score > current_best.score:
                    best_by_key[key] = result

    ranked = sorted(
        best_by_key.values(),
        key=lambda r: (-_word_coverage(r, query_words), -r.score),
    )
    logger.debug(
        "search: query=%r terms=%r found=%d", query, terms, len(ranked)
    )
    return ranked[:max_results]


# ── Private helpers ───────────────────────────────────────────────────────────

def _word_coverage(result: SearchResult, query_words: set[str]) -> float:
    """Fraction of the query's distinct words present in this result's own text."""
    if not query_words:
        return 0.0
    target = f"{result.name} {result.detail}"
    matched = sum(1 for word in query_words if score_match(target, word) > 0)
    return matched / len(query_words)


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

    for comp_row in reader.list_components():
        comp_name = comp_row.get("c.name", "")
        if not comp_name:
            continue
        s = score_match(comp_name, term)
        if s > 0:
            results.append(SearchResult(
                type="Component", name=comp_name,
                detail=comp_row.get("c.comp_type", ""),
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

    for text in reader.list_texts():
        content = text.get("t.content", "")
        s = score_match(content, term)
        if s > 0:
            results.append(SearchResult(
                type="UIText", name=content, detail=text.get("t.source", ""),
                id=text.get("t.id", content), doc=doc_name, score=s,
            ))

    return results
