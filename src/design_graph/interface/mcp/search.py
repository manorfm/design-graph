"""
Cross-prototype search with relevance scoring.

Replaces the legacy CONTAINS-only literal search with a scored, alias-aware
search that ranks exact > prefix > suffix > contains matches.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from weakref import WeakKeyDictionary

from design_graph.model.graph.reader import GraphReader
from design_graph.interface.mcp.aliases import get_aliases
from design_graph.interface.mcp.identifiers import identifiers_in

logger = logging.getLogger(__name__)

MAX_TOKENS_IN_SEARCH_QUERY_EXPANSION = 6


@dataclass
class SearchResult:
    type: str    # "Screen" | "Component" | "Token" | "UIText"
    name: str
    detail: str
    id: str      # unique identifier within its type
    doc: str     # prototype/document name
    score: int   # 0–100
    word_coverage: float = 1.0  # fraction of the query's distinct words this result actually matched
    # Graph context for Component results, so an agent can tell where a hit
    # lives without a follow-up get_component_spec() call. Reuses the same
    # reader methods get_component_spec already calls for this — empty for
    # every non-Component result type.
    parents: list[str] = field(default_factory=list)
    screens_using: list[str] = field(default_factory=list)
    # Whether the whole query (or an alias of it) appears in what this result
    # names — a result that only shares some of its words does not confirm it exists.
    has_phrase: bool = False
    haystack: str = field(default="", repr=False)


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
                key = (result.doc, result.type, result.id)
                current_best = best_by_key.get(key)
                if current_best is None or result.score > current_best.score:
                    best_by_key[key] = result

    phrases = _phrases(query, aliases)
    for result in best_by_key.values():
        result.word_coverage = _word_coverage(result, query_words)
        result.has_phrase = any(phrase in result.haystack for phrase in phrases)

    ranked = sorted(
        best_by_key.values(),
        key=lambda r: (not r.has_phrase, -r.word_coverage, -r.score, _TYPE_RANK.get(r.type, 9)),
    )
    top = ranked[:max_results]

    # Hierarchy lookups cost a graph query each, so they only run on the
    # final, already-deduplicated, already-capped result set — never once
    # per matched query term.
    readers_by_doc = dict(readers)
    for result in top:
        if result.type == "Component":
            reader = readers_by_doc[result.doc]
            result.parents = reader.get_component_parents(result.id)
            result.screens_using = reader.find_screens_using_comp_transitively(result.id)

    logger.debug(
        "search: query=%r terms=%r found=%d", query, terms, len(ranked)
    )
    return top


# ── Private helpers ───────────────────────────────────────────────────────────

# Names first, then what lives inside screens, then copy, then code.
_TYPE_RANK = {
    "Screen": 0, "Component": 0, "Section": 1, "Prop": 1, "Token": 1, "Ação": 1, "Estado": 1, "UIText": 2, "CssClass": 2, "Código": 3,
}


def _phrases(query: str, aliases: dict[str, list[str]]) -> list[str]:
    """The query as one phrase, and what it means in the other language when it is one known word."""
    phrase = " ".join(query.lower().split())
    return [phrase, *(e.lower() for key, expansions in aliases.items() if key == phrase for e in expansions)]


def _word_coverage(result: SearchResult, query_words: set[str]) -> float:
    """Fraction of the query's distinct words present in this result's own text."""
    if not query_words:
        return 0.0
    target = f"{result.name} {result.detail}"
    matched = sum(1 for word in query_words if score_match(target, word) > 0)
    return matched / len(query_words)


@dataclass(frozen=True)
class _IndexEntry:
    """One searchable graph entity and the strings a term is matched against."""

    type: str
    name: str
    detail: str
    id: str
    keys: tuple[str, ...]


# One index per reader, built on its first search. The MCP server replaces
# its readers when a graph is rebuilt, so an index never outlives its graph.
_INDEXES: WeakKeyDictionary[GraphReader, list[_IndexEntry]] = WeakKeyDictionary()


def _index_of(reader: GraphReader) -> list[_IndexEntry]:
    index = _INDEXES.get(reader)
    if index is None:
        index = _INDEXES[reader] = _build_index(reader)
    return index


def _build_index(reader: GraphReader) -> list[_IndexEntry]:
    entries = [_IndexEntry("Screen", s["name"], "", s["name"], (s["name"],)) for s in reader.list_screens()]
    entries += [
        _IndexEntry("Component", c["c.name"], c.get("c.comp_type", ""), c["c.name"], (c["c.name"], c.get("c.comp_type", "")))
        for c in reader.list_components() if c.get("c.name")
    ]
    sections = {s["id"]: s for s in reader.list_sections()}
    entries += [
        _IndexEntry("Section", s["name"], f"tela {s['screen']}", s["id"], (s["name"],)) for s in sections.values()
    ]
    entries += [
        _IndexEntry("Prop", p["prop"], f"de {p['component']}", f"{p['component']}.{p['prop']}", (p["prop"],))
        for p in reader.list_props()
    ]
    entries += _code_entries(reader.list_sources())
    entries += [
        _IndexEntry("Ação", f"{a['trigger']} em {a['element']}", f"{a['owner']}: {a['effect']}",
                    f"{a['owner']}:{a['trigger']}:{a['element']}:{a['handler']}", (a["handler"], a["effect"]))
        for a in reader.list_actions()
    ]
    entries += [
        _IndexEntry("Estado", s["name"], f"{s['owner']}, inicial {s['initial']}", f"{s['owner']}:{s['name']}", (s["name"],))
        for s in reader.list_states()
    ]
    for token in reader.get_tokens():
        label, value = token.get("t.label", ""), token.get("t.value", "")
        entries.append(_IndexEntry("Token", label, value, token.get("t.id", label), (label, value)))
    for text in reader.list_texts():
        content = text.get("t.content", "")
        entries.append(_IndexEntry("UIText", content, _place(text.get("t.source", ""), sections),
                                   text.get("t.id", content), (content,)))
    entries += [
        _IndexEntry("CssClass", name, "classe CSS compartilhada", f"class:{name}", (name,))
        for name in reader.list_shared_style_classes()
    ]
    return entries


def _place(source: str, sections: dict[str, dict]) -> str:
    """Where a text lives, readable: "Tela › Seção" for a section's, the component's name otherwise."""
    section = sections.get(source)
    return f"{section['screen']} › {section['name']}" if section else source


def _code_entries(sources: list[dict]) -> list[_IndexEntry]:
    """Each name the code of a component or screen uses (handlers, state, helpers), once per owner."""
    entries = []
    for source in sources:
        for identifier in identifiers_in(source["source_code"]):
            entries.append(_IndexEntry("Código", identifier, f"no código de {source['name']}",
                                       f"{source['name']}:{identifier}", (identifier,)))
    return entries


def _search_reader(reader: GraphReader, doc_name: str, term: str) -> list[SearchResult]:
    """Search one reader's index for one query term."""
    results = []
    for entry in _index_of(reader):
        score = max(score_match(key, term) for key in entry.keys)
        if score > 0:
            results.append(SearchResult(
                type=entry.type, name=entry.name, detail=entry.detail, id=entry.id, doc=doc_name, score=score,
                haystack=" ".join(" ".join(key.lower().split()) for key in entry.keys),
            ))
    return results
