"""Checking an implementation an agent wrote against a component's stored spec."""

from __future__ import annotations

import logging

from design_graph.model.entities import StyleState
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
