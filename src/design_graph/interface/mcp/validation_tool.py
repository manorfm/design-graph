"""Checking an implementation an agent wrote against a component's stored spec."""

from __future__ import annotations

import logging

from design_graph.model.entities import StyleState
from design_graph.model.graph.reader import GraphReader
from design_graph.capture.html_prototype.extraction.component_extractor import extract_component
from design_graph.capture.html_prototype.parsing.js_parser import find_all_boundaries
from design_graph.interface.mcp.notices import truncation_notice

logger = logging.getLogger(__name__)


# validate_component_implementation re-runs the same regex-based extractor
# used for a whole prototype bundle, but over agent-submitted text instead
# of a local file — the one MCP tool whose input isn't bounded by "however
# big this local prototype happens to be". A real component's stored
# source_code is itself capped at MAX_SOURCE_CODE_CHARS (8_000); this is a
# generous multiple of that, not a tight fit, so it never rejects a
# legitimate submission while still bounding the computational cost of an
# oversized jsx_source (accidental or adversarial, e.g. an agent misled by
# prompt injection inside the prototype's own HTML).
MAX_VALIDATION_SOURCE_CHARS = 20_000


# Synthetic wrapper name for validate_component_implementation. Must be
# plain PascalCase, no leading underscore — find_all_boundaries only
# recognizes function names matching the same convention real React
# component names use, exactly as it would for any bundle it parses.
_VALIDATION_WRAPPER_NAME = "DesignGraphValidationCandidate"


def _extract_validation_candidate(jsx_source: str):
    """
    Re-extract an agent-submitted JSX expression using the same
    component_extractor.extract_component the build pipeline itself uses —
    wrapped in a synthetic function declaration so find_all_boundaries can
    locate it (extract_component has no entry point for bare JSX; a real
    prototype bundle never contains one either).

    No rule_map/tag_rule_map/palette is passed: those come from the whole
    prototype's own stylesheet, which doesn't exist for a standalone
    snippet. Concretely, this means className-resolved styles (custom CSS
    classes and Tailwind color utilities) are NOT captured here even when
    they would be in a real build — only inline style={{}} objects, JSX
    child references, and text content are reliably extracted. Spread
    references (style={{...shared}}) also resolve to nothing, for the same
    "no whole-file context" reason component_extractor's own spread
    resolution already documents.
    """
    synthetic_js = f"function {_VALIDATION_WRAPPER_NAME}() {{\n  return (\n{jsx_source}\n  );\n}}"
    boundaries = find_all_boundaries(synthetic_js)
    if not boundaries:
        return None
    return extract_component(synthetic_js, boundaries[0], 1, {})




def validate_component_implementation(
    reader: GraphReader, name: str, jsx_source: str,
) -> str:
    if not jsx_source.strip():
        return "jsx_source vazio — nada para comparar."
    if len(jsx_source) > MAX_VALIDATION_SOURCE_CHARS:
        return (
            f"jsx_source muito grande ({len(jsx_source)} caracteres, limite "
            f"{MAX_VALIDATION_SOURCE_CHARS}). Passe só a expressão JSX do "
            f"componente, não o arquivo inteiro."
        )

    spec = reader.get_component_spec(name)
    if not spec:
        return f"Componente '{name}' não encontrado. Use search('{name}') para explorar."
    cname = spec["c.name"]

    candidate = _extract_validation_candidate(jsx_source)
    if candidate is None:
        return (
            "Não foi possível interpretar jsx_source como JSX válido "
            "(passe a expressão JSX, ex.: o que get_full_jsx devolve, não uma "
            "declaração de função completa)."
        )

    lines = [
        f"# Validação: {cname}",
        "> Best-effort: não verifica estilos vindos de classes CSS do protótipo "
        "nem cores Tailwind (ex. bg-blue-500) — só estilos inline e utilitários "
        "de layout têm cobertura confiável aqui. Um relatório limpo não é prova "
        "de correspondência pixel-perfeita.\n",
    ]

    stored_children = set(spec.get("children", []))
    candidate_children = set(candidate.child_refs)
    missing_children = sorted(stored_children - candidate_children)
    extra_children = sorted(candidate_children - stored_children)
    if missing_children:
        lines.append(f"⚠ **Filhos ausentes na implementação**: {', '.join(missing_children)}")
    if extra_children:
        lines.append(f"ℹ **Filhos novos (não estavam na spec original)**: {', '.join(extra_children)}")
    if not missing_children and not extra_children and stored_children:
        lines.append("✅ Filhos batem com a spec.")

    stored_default = {
        (s["property"], s["value"])
        for s in spec.get("styles_by_state", {}).get("default", [])
    }
    candidate_default = {
        (s.property, s.value) for s in candidate.styles if s.state == StyleState.DEFAULT
    }
    missing_styles = sorted(stored_default - candidate_default)
    if missing_styles:
        lines.append("\n⚠ **Estilos default ausentes na implementação** (property, value):")
        for prop, val in missing_styles[:15]:
            lines.append(f"- `{prop}`: `{val}`")
        notice = truncation_notice(len(missing_styles), 15, recoverable_via=cname)
        if notice:
            lines.append(notice)
    elif stored_default:
        lines.append("\n✅ Estilos default inline batem com a spec (dentro do que é verificável).")

    stored_texts = {t["t.content"] for t in spec.get("texts", [])}
    candidate_texts = {t.content for t in candidate.texts}
    missing_texts = sorted(stored_texts - candidate_texts)
    if missing_texts:
        lines.append("\n⚠ **Textos ausentes na implementação**:")
        for t in missing_texts[:10]:
            lines.append(f'- "{t}"')
        notice = truncation_notice(len(missing_texts), 10, recoverable_via=cname, tool="get_full_texts")
        if notice:
            lines.append(notice)
    elif stored_texts:
        lines.append("\n✅ Textos batem com a spec.")

    logger.debug("tools: validate_component_implementation(%s) — rendered", cname)
    return "\n".join(lines)
