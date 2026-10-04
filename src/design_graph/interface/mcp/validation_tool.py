"""Checking an implementation an agent wrote against a component's stored spec."""

from __future__ import annotations

import logging

from design_graph.model.entities import ExtractedComponent, StyleState
from design_graph.model.graph.reader import GraphReader
from design_graph.interface.mcp.notices import truncation_notice
from design_graph.pipeline.coordinator import UnsupportedPrototypeError, capture_fragment

logger = logging.getLogger(__name__)


# The one tool whose input is agent-submitted text rather than a local file:
# it is read by the same extractor a whole prototype goes through, so its
# size is bounded here. A stored component source is capped at 8_000 chars;
# this generous multiple never rejects a real submission while bounding the
# cost of an oversized one (accidental or adversarial, e.g. an agent misled by
# prompt injection inside the prototype itself).
MAX_VALIDATION_SOURCE_CHARS = 20_000


def validate_component_implementation(reader: GraphReader, name: str, source: str) -> str:
    if not source.strip():
        return "source vazio — nada para comparar."
    if len(source) > MAX_VALIDATION_SOURCE_CHARS:
        return (
            f"source muito grande ({len(source)} caracteres, limite "
            f"{MAX_VALIDATION_SOURCE_CHARS}). Passe só o fonte do componente, "
            f"não o arquivo inteiro."
        )

    info = reader.model_info()
    if not info:
        return (
            "Este protótipo foi gerado sem registrar sua captura — reconstrua com "
            "`design-graph --force <proto.html>` para validar implementações."
        )

    spec = reader.get_component_spec(name)
    if not spec:
        return f"Componente '{name}' não encontrado. Use search('{name}') para explorar."
    cname = spec["c.name"]

    try:
        candidate = capture_fragment(info["capture"], source)
    except UnsupportedPrototypeError:
        return f"Validação indisponível: a captura '{info['capture']}' deste protótipo não está instalada."
    if candidate is None:
        return (
            f"Não foi possível ler `source` no formato deste protótipo ({info['capture']}) — "
            "passe o fonte do componente no mesmo formato que get_full_jsx devolve."
        )

    lines = [
        f"# Validação: {cname}",
        "> Best-effort: não verifica estilos vindos de classes CSS do protótipo "
        "nem cores Tailwind (ex. bg-blue-500) — só estilos inline e utilitários "
        "de layout têm cobertura confiável aqui. Um relatório limpo não é prova "
        "de correspondência pixel-perfeita.\n",
    ]

    lines.extend(_children_lines(spec, candidate))
    lines.extend(_style_lines(spec, candidate, cname))
    lines.extend(_text_lines(spec, candidate, cname))

    logger.debug("tools: validate_component_implementation(%s) — rendered", cname)
    return "\n".join(lines)


def _children_lines(spec: dict, candidate: ExtractedComponent) -> list[str]:
    stored, written = set(spec.get("children", [])), set(candidate.child_refs)
    missing, extra = sorted(stored - written), sorted(written - stored)
    lines = []
    if missing:
        lines.append(f"⚠ **Filhos ausentes na implementação**: {', '.join(missing)}")
    if extra:
        lines.append(f"ℹ **Filhos novos (não estavam na spec original)**: {', '.join(extra)}")
    if not missing and not extra and stored:
        lines.append("✅ Filhos batem com a spec.")
    return lines


def _style_lines(spec: dict, candidate: ExtractedComponent, cname: str) -> list[str]:
    stored = {(s["property"], s["value"]) for s in spec.get("styles_by_state", {}).get("default", [])}
    written = {(s.property, s.value) for s in candidate.styles if s.state == StyleState.DEFAULT}
    missing = sorted(stored - written)
    if not missing:
        return ["\n✅ Estilos default inline batem com a spec (dentro do que é verificável)."] if stored else []
    lines = ["\n⚠ **Estilos default ausentes na implementação** (property, value):"]
    lines.extend(f"- `{prop}`: `{val}`" for prop, val in missing[:15])
    notice = truncation_notice(len(missing), 15, recoverable_via=cname)
    return lines + ([notice] if notice else [])


def _text_lines(spec: dict, candidate: ExtractedComponent, cname: str) -> list[str]:
    stored = {t["t.content"] for t in spec.get("texts", [])}
    missing = sorted(stored - {t.content for t in candidate.texts})
    if not missing:
        return ["\n✅ Textos batem com a spec."] if stored else []
    lines = ["\n⚠ **Textos ausentes na implementação**:"]
    lines.extend(f'- "{t}"' for t in missing[:10])
    notice = truncation_notice(len(missing), 10, recoverable_via=cname, tool="get_full_texts")
    return lines + ([notice] if notice else [])

