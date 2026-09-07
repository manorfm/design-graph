# Plan C42

## T97 — `extraction/section_extractor.py`

- `_find_balanced_tag_end(window, tag, start)` generaliza
  `_find_balanced_div_end` (mantido como wrapper — assinatura pública
  intacta, ainda importado direto por `test_section_extractor_fallbacks.py`).
- `_SEMANTIC_CHROME_TAGS = ("aside", "nav", "header", "footer")` +
  `_semantic_chrome_candidates(window)` — nova terceira fonte de
  candidato em `_detect_by_structure`, mesclada com as duas já existentes
  (padding literal, padding resolvido por classe) antes do dedup por
  sobreposição.
- `_class_based_name(block)` — nome a partir do `className` da tag raiz
  do bloco (`\A<tag ... className=\{?["'](classe)`, aceita o `{` opcional
  antes da aspa pra cobrir `className={"x" + ...}`). Usado como primeira
  opção em `_detect_by_structure`'s naming, antes do texto visível e do
  fallback posicional.

Testes novos em `tests/unit/extraction/test_section_extractor.py`
(`TestSemanticChromeTagsAsSections`): `<aside>` sem padding vira seção;
nome vem da expressão de `className`; `<div className="topbar">` recebe
nome "Topbar" em vez do texto "Menu"; `<main>` continua fora de escopo;
tela sem tag semântica nenhuma não muda de comportamento.

## Validação end-to-end — executada em 2026-09-07

```
pytest tests/unit -q                              → 1950 passed
pytest tests/unit tests/integration \
       tests/test_architecture_guardrails.py -q   → 2127 passed
design-graph "toToggle v2.6.html" --force          → screens=10 sections=21
design-graph validate --db ".../toToggle v2.6.db"  → status=ok errors=0 warnings=0
```

Verificado manualmente contra `App` no `toToggle v2.6` real: `Sidebar`
(novo, antes inexistente) e `Topbar` (renomeado de "Menu") confirmados via
`get_screen_full`/`get_section`.
