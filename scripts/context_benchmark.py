#!/usr/bin/env python3
"""
Context benchmark — how much of a prototype the MCP tools let an agent
recover, and at what context cost. Deterministic: no LLM involved.

For one prototype it builds a fresh graph and measures:

  texts     visible copy of the pages that is indexed as text in the graph
  styles    literal style declarations an agent can read in the responses it
            gets while assembling each screen
  screens   per screen: characters returned by get_screen_full plus every
            call its recovery hints point to, compared with the original
            markup; and how many cuts those responses announce
  searches  real search queries (from the metrics log) checked against the
            prototype: does a term that exists come back, and does a term
            that does not exist come back empty?
  build     total time, per-phase time and write errors

Ground truth is read straight from the pages' markup — never through the
capture being measured. Formats whose markup is produced at runtime
(bundled React) have no such ground truth: their coverage is reported as
not available instead of an approximation.

usage: python scripts/context_benchmark.py PROTOTYPE.html [--out DIR] [--queries FILE]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from enum import Enum
from pathlib import Path

import kuzu
from bs4 import BeautifulSoup, Comment

from design_graph.capture.base import PrototypeDocument
from design_graph.capture.bundler import read_bundle
from design_graph.capture.dc_canvas.canvas import read_boards
from design_graph.capture.dc_canvas.page import DcPage, read_page
from design_graph.capture.html_prototype.parsing.js_parser import find_all_boundaries
from design_graph.capture.html_prototype.parsing.source_loader import decompose
from design_graph.capture.registry import capture_for
from design_graph.interface.mcp.metrics import read_records
from design_graph.interface.mcp.tools import ToolDispatcher
from design_graph.model.graph.reader import GraphReader
from design_graph.pipeline.build_progress import SilentBuildReporter
from design_graph.pipeline.coordinator import run_pipeline

_NOT_RENDERED = {"script", "style", "helmet", "template"}
_INTERPOLATION = "{{"
_RE_STYLE_ATTRIBUTE = re.compile(r'style="([^"]*)"')
_RE_STYLE_ROW = re.compile(r"^\|\s*([a-z-]+)\s*\|\s*([^|]+?)\s*\|\s*$", re.MULTILINE)
_RE_STYLE_ITEM = re.compile(r"`([a-z-]+)`: `([^`]+)`")
_RE_RECOVERY_CALL = re.compile(r"(get_full_source|get_full_styles|get_full_texts|get_component_data)\(([^()]*)\)")
_RE_KEYWORD_ARG = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
_RE_LIST_CUT = re.compile(r"\+\d+ mais")
_RE_SOURCE_CUT = re.compile(r"\+\d+ caracteres")


class SearchVerdict(str, Enum):
    FOUND = "found"
    PARTIAL = "partial"
    NOTHING = "nothing"


# ── Ground truth ──────────────────────────────────────────────────────────────

def visible_texts(markup: str) -> set[str]:
    """Every literal text node a reader of the page sees, whitespace-collapsed."""
    texts = set()
    for node in BeautifulSoup(markup, "html.parser").find_all(string=True):
        if isinstance(node, Comment) or any(p.name in _NOT_RENDERED for p in node.parents if p.name):
            continue
        text = " ".join(node.split())
        if text and _INTERPOLATION not in text:
            texts.add(text)
    return texts


def style_declarations(markup: str) -> set[str]:
    """Every literal inline style declaration, normalized as `property: value`."""
    return {
        declaration
        for attribute in _RE_STYLE_ATTRIBUTE.findall(markup)
        for declaration in map(_normalized_declaration, attribute.split(";"))
        if declaration
    }


def _normalized_declaration(raw: str) -> str | None:
    prop, sep, value = raw.partition(":")
    prop, value = prop.strip().lower(), " ".join(value.split())
    if not sep or not prop or not value or _INTERPOLATION in value:
        return None
    return f"{prop}: {value}"


def page_markups(document: PrototypeDocument, capture: str) -> dict[str, str] | None:
    """Screen name → the markup that screen renders, when the format has it statically."""
    if capture != "dc_canvas":
        return None
    return {name: page.markup for name, page in _dc_pages(document).items()}


def _dc_pages(document: PrototypeDocument) -> dict[str, DcPage]:
    bundle = read_bundle(document.text)
    pages = {}
    for board in read_boards(bundle.template):
        page = read_page(bundle.entry(board.page_id).decode("utf-8", errors="replace"))
        if page is not None:
            pages[board.name] = page
    return pages


def round_trip(document: PrototypeDocument, capture: str, reader: GraphReader) -> dict:
    """
    How many screens and components the graph returns exactly as written:
    every piece of the prototype that defines them (a DC page's markup, CSS
    and logic; each React function declared under the name) appears verbatim
    in the stored source.
    """
    if capture == "dc_canvas":
        written = {
            name: [part for part in (page.markup, page.styles, page.logic) if part]
            for name, page in _dc_pages(document).items()
        }
    else:
        js = decompose(document).js
        written = {}
        for boundary in find_all_boundaries(js):
            written.setdefault(boundary.name, []).append(js[boundary.start:boundary.end])
    names = [c["c.name"] for c in reader.list_components()] + [s["name"] for s in reader.list_screens()]
    checked = verbatim = 0
    for name in names:
        stored = reader.get_full_source(name)
        if name not in written or not stored:
            continue
        checked += 1
        verbatim += all(part in stored["source_code"] for part in written[name])
    return {"checked": checked, "verbatim": verbatim, "rate": verbatim / checked if checked else None}


# ── Reading responses ─────────────────────────────────────────────────────────

def coverage(truth: set[str], recovered: set[str]) -> float | None:
    return len(truth & recovered) / len(truth) if truth else None


def cut_notices(response: str) -> dict[str, int]:
    return {
        "list": len(_RE_LIST_CUT.findall(response)),
        "source": len(_RE_SOURCE_CUT.findall(response)),
        "capture": response.count("Extração truncada"),
    }


def recovery_calls(response: str) -> list[tuple[str, dict]]:
    """Each distinct call a response tells the agent to make to recover what it cut."""
    calls: list[tuple[str, dict]] = []
    for tool, raw in _RE_RECOVERY_CALL.findall(response):
        keywords = dict(_RE_KEYWORD_ARG.findall(raw))
        args = keywords or {"name": raw.strip().strip("'\"` ")}
        if args.get("name") != "" and (tool, args) not in calls:
            calls.append((tool, args))
    return calls


def classify_search(response: str) -> SearchVerdict:
    if response.startswith("Nenhum resultado"):
        return SearchVerdict.NOTHING
    if "Nenhum resultado cobre todas as palavras" in response:
        return SearchVerdict.PARTIAL
    return SearchVerdict.FOUND


def _declarations_shown(response: str) -> set[str]:
    """Style declarations a response shows — in source blocks, style tables and style lists."""
    shown = style_declarations(response)
    rows = _RE_STYLE_ROW.findall(response) + _RE_STYLE_ITEM.findall(response)
    shown.update(filter(None, (_normalized_declaration(f"{p}: {v}") for p, v in rows)))
    return shown


# ── Measuring ─────────────────────────────────────────────────────────────────

class _PhaseTimes(SilentBuildReporter):
    """Build reporter that keeps how long each pipeline phase took."""

    def __init__(self) -> None:
        self.phases: dict[str, float] = {}

    def phase_completed(self, name: str, *, elapsed_seconds: float, total: int = 0) -> None:
        self.phases[name] = round(elapsed_seconds, 3)


def _build(html: Path, workdir: Path) -> tuple[Path, dict]:
    db_path = workdir / f"{html.stem}.db"
    timer, started = _PhaseTimes(), time.perf_counter()
    stats = asyncio.run(run_pipeline(
        html, db_path, workdir / f"{html.stem}.db.state.json", force=True, reporter=timer,
    ))
    return db_path, {
        "seconds": round(time.perf_counter() - started, 3),
        "phases": timer.phases,
        "write_errors": stats.write_errors if stats else 0,
    }


def _screen_report(tools: ToolDispatcher, name: str, markup: str | None) -> tuple[dict, str]:
    screen_full = tools.dispatch("get_screen_full", {"name": name}, "bench")
    responses = [screen_full] + [tools.dispatch(tool, args, "bench") for tool, args in recovery_calls(screen_full)]
    corpus = "\n".join(responses)
    response_chars = sum(map(len, responses))
    original = len(markup) if markup is not None else None
    return {
        "response_chars": response_chars,
        "original_chars": original,
        "ratio": response_chars / original if original else None,
        "cuts": cut_notices(screen_full),
        "recovery_calls": len(responses) - 1,
    }, corpus


def _search_report(tools: ToolDispatcher, queries: list[str], prototype_text: str) -> dict:
    haystack = prototype_text.lower()
    checked = []
    for query in dict.fromkeys(q.strip() for q in queries if q.strip()):
        verdict = classify_search(tools.dispatch("search", {"query": query}, "bench"))
        exists = query.lower() in haystack
        correct = verdict == (SearchVerdict.FOUND if exists else SearchVerdict.NOTHING)
        checked.append({"query": query, "exists": exists, "verdict": verdict.value, "correct": correct})
    return {"queries": checked, "correct": sum(q["correct"] for q in checked), "total": len(checked)}


def benchmark(html: Path, workdir: Path, queries: list[str]) -> dict:
    document = PrototypeDocument.read(html)
    capture = capture_for(document).name
    markups = page_markups(document, capture)
    db_path, build = _build(html, workdir)
    reader = GraphReader(kuzu.Connection(kuzu.Database(str(db_path), read_only=True)))
    tools = ToolDispatcher([("bench", reader)])

    screens, shown_styles, truth_styles = {}, set(), set()
    for screen in reader.list_screens():
        markup = markups.get(screen["name"]) if markups else None
        screens[screen["name"]], corpus = _screen_report(tools, screen["name"], markup)
        if markup is not None:
            declarations = style_declarations(markup)
            truth_styles |= declarations
            shown_styles |= declarations & _declarations_shown(corpus)

    truth_texts = set().union(*map(visible_texts, markups.values())) if markups else set()
    indexed_texts = {" ".join(t["t.content"].split()) for t in reader.list_texts()}
    prototype_text = "\n".join(markups.values()) if markups else document.text
    return {
        "prototype": html.stem,
        "capture": capture,
        "build": build,
        "texts": _coverage_entry(truth_texts, indexed_texts, markups is not None),
        "styles": _coverage_entry(truth_styles, shown_styles, markups is not None),
        "round_trip": round_trip(document, capture, reader),
        "screens": screens,
        "searches": _search_report(tools, queries, prototype_text),
    }


def _coverage_entry(truth: set[str], recovered: set[str], measurable: bool) -> dict:
    if not measurable:
        return {"truth": None, "recovered": None, "coverage": None}
    return {"truth": len(truth), "recovered": len(truth & recovered), "coverage": coverage(truth, recovered)}


# ── Reporting ─────────────────────────────────────────────────────────────────

def render_markdown(report: dict) -> str:
    totals, searches = _screen_totals(report["screens"].values()), report["searches"]
    assembly = f"{totals['responded']:,}"
    if totals["original"]:
        assembly += f" ({totals['responded'] / totals['original']:.0%} do original)"
    lines = [
        f"# Context benchmark — {report['prototype']} ({report['capture']})",
        "",
        "| Métrica | Valor |",
        "|---|---|",
        f"| Build | {report['build']['seconds']} s · erros de gravação {report['build']['write_errors']} |",
        f"| Textos indexados | {_coverage_cell(report['texts'])} |",
        f"| Estilos legíveis ao montar as telas | {_coverage_cell(report['styles'])} |",
        f"| Fontes devolvidos como escritos | {_round_trip_cell(report.get('round_trip'))} |",
        f"| Caracteres para montar todas as telas | {assembly} |",
        f"| Cortes anunciados | listas {totals['list']} · fontes {totals['source']} · captura {totals['capture']} |",
        f"| Buscas corretas | {searches['correct']}/{searches['total']} |",
    ]
    wrong = [q for q in searches["queries"] if not q["correct"]]
    if wrong:
        lines += ["", "## Buscas erradas", ""]
        lines += [f"- `{q['query']}` — existe: {'sim' if q['exists'] else 'não'}, resposta: {q['verdict']}" for q in wrong]
    return "\n".join(lines) + "\n"


def _screen_totals(screens) -> dict[str, int]:
    screens = list(screens)
    totals = {kind: sum(s["cuts"][kind] for s in screens) for kind in ("list", "source", "capture")}
    totals["responded"] = sum(s["response_chars"] for s in screens)
    totals["original"] = sum(s["original_chars"] or 0 for s in screens)
    return totals


def _round_trip_cell(entry: dict | None) -> str:
    if not entry or entry["rate"] is None:
        return "n/d"
    return f"{entry['rate']:.0%} ({entry['verbatim']}/{entry['checked']})"


def _coverage_cell(entry: dict) -> str:
    if entry["coverage"] is None:
        return "n/d (sem gabarito estático para este formato)"
    return f"{entry['coverage']:.0%} ({entry['recovered']}/{entry['truth']})"


def _queries_for(prototype: str, extra_file: Path | None) -> list[str]:
    logged = [
        str(r.arguments.get("query", "")) for r in read_records()
        if r.tool == "search" and r.prototype == prototype
    ]
    extra = extra_file.read_text(encoding="utf-8").splitlines() if extra_file else []
    return logged + extra


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("prototype", type=Path)
    parser.add_argument("--out", type=Path, default=Path(".bench"), help="Directory for the report (default: .bench)")
    parser.add_argument("--queries", type=Path, default=None, help="Extra search queries, one per line")
    parser.add_argument("--name", default=None, help="Prototype name in the metrics log (default: file stem)")
    args = parser.parse_args(argv)
    if not args.prototype.is_file():
        parser.error(f"prototype not found: {args.prototype}")

    args.out.mkdir(parents=True, exist_ok=True)
    workdir = args.out / "graphs"
    workdir.mkdir(exist_ok=True)
    report = benchmark(args.prototype, workdir, _queries_for(args.name or args.prototype.stem, args.queries))
    name = f"bench-{args.prototype.stem}"  # stems like "v2.6.4" have dots: never use with_suffix
    (args.out / f"{name}.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    markdown = render_markdown(report)
    (args.out / f"{name}.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
