# Spec C33 — Validação round-trip (spike + implementação)

## Contexto

Nona e última de 9 changes (C25–C33) motivada pela auditoria técnica
completa do pipeline (ver C25/spec.md). Diferente dos changes anteriores,
este exigia um **spike antes de qualquer código de produção**: o plano
identificou risco real de inviabilidade técnica, com critério de ir/não-ir
explícito.

## Spike — resultado

Executado diretamente contra `extract_component`/`find_all_boundaries`
(`extraction/component_extractor.py`, `parsing/js_parser.py`), fora de
qualquer bundle real:

1. **JSX solto (sem função ao redor) não funciona** — confirmado:
   `find_all_boundaries("<button>...</button>")` retorna `[]`.
   `extract_component` não tem ponto de entrada para JSX sem função — nem
   precisaria ter, já que nenhum bundle real contém isso. **Mitigação
   viável**: envolver o `jsx_source` recebido do agente numa declaração de
   função sintética antes de extrair.

2. **Nome do wrapper precisa ser PascalCase sem underscore inicial** —
   descoberto durante o spike (não previsto no plano original):
   `find_all_boundaries` só reconhece nomes de função no mesmo formato que
   nomes reais de componente React usam; `__ValidationCandidate__` não é
   reconhecido, `ValidationCandidate` é. Achado incidental do próprio
   spike, corrigido antes de qualquer teste automatizado existir.

3. **Spread (`...sharedStyle`) não resolve — confirmado, é real.**
   `_find_const_object_body` busca `const sharedStyle = {` no "arquivo
   inteiro"; para um snippet isolado não há arquivo — o spread
   simplesmente não encontra nada e a propriedade correspondente não
   aparece (comportamento documentado de fallback, não uma exceção).

4. **Classes CSS customizadas do protótipo não resolvem — confirmado, é
   real.** `resolve_classes` precisa de `rule_map` (vindo do CSS real do
   protótipo); sem ele, só `_TAILWIND_BUILTINS` (mapa estático) responde.

5. **Achado não previsto no plano**: `_TAILWIND_BUILTINS` cobre só
   utilitários de layout/espaçamento/dimensão — **não inclui cores**
   (`bg-blue-500` não resolve mesmo sem `rule_map`, `flex` resolve).
   Verificado por execução direta, não por leitura de código. Isso é mais
   restritivo do que o plano original assumia.

**Critério de ir/não-ir**: o plano dizia "se re-extração completa não for
viável sem reescrever os 3 subsistemas, o v1 nasce escopado como
comparação heurística". A leitura do spike é intermediária, não um "sim"
nem um "não" limpo: re-extração real **é viável e produz sinal correto**
para estilos inline, `child_refs`, texto e utilitários Tailwind de
layout — mas tem lacunas reais e specíficas (spread, CSS customizado,
cores Tailwind) que **não são recuperáveis** sem o contexto do arquivo
original. Decisão: **ir com re-extração real**, não com comparação
heurística por palavra-chave (mais fraca) — mas expor as lacunas
explicitamente na descrição da tool e no próprio relatório, nunca
apresentar o resultado como verificação completa.

## Solução proposta

| Task | Camada |
|---|---|
| T71 | `mcp/tools.py` (`validate_component_implementation`) |

**T71** — nova tool MCP. `_extract_validation_candidate(jsx_source)`
envolve o texto recebido em `function DesignGraphValidationCandidate() {
return (\n<jsx_source>\n); }` e roda o mesmíssimo `extract_component` que o
pipeline de build usa — sem `rule_map`/`tag_rule_map`/`palette` (não
existem para um snippet isolado). `validate_component_implementation`
busca a spec já persistida (`reader.get_component_spec`) e compara três
eixos contra o candidato re-extraído: `children` (diferença de conjuntos —
ausentes e novos), estilos em estado `default` (pares
propriedade/valor ausentes na implementação) e textos (conteúdo ausente).
A saída Markdown sempre abre com o aviso de limitação, e cada seção reporta
"✅ bate" só quando não há divergência E havia algo para comparar (uma
spec vazia não produz um "✅" vazio enganoso).

## Cobertura de testes exigida

- `TestExtractValidationCandidate` (3 casos): estilo inline extraído
  corretamente após o wrap; `child_refs` capturados; spread não resolve
  (comportamento documentado, não falha) — este último é o teste que
  materializa o achado #3 do spike como regressão permanente.
- `TestValidateComponentImplementationTool` (7 casos): tool presente nas
  definições, schema exige `name`+`jsx_source`, `jsx_source` vazio,
  componente desconhecido, estilo batendo (sem falso positivo de
  "ausente"), estilo faltando (sinalizado corretamente), aviso de
  limitação sempre presente na saída.

Suíte completa (`pytest tests/unit/ -q`, `pytest tests/integration/ -q`) sem
regressão e guardrails (`pytest tests/test_architecture_guardrails.py -q`)
intactas; rebuild real contra `iPede Manager v21.2.html` (DB descartável em
`/tmp`) reportado no `plan.md` — sem mudança de métrica esperada (mudança é
inteiramente de leitura/API, mesma camada que C31).

## Segurança

`mcp/tools.py` passa a importar de `extraction/`/`parsing/` — verificado
contra as guardrails de arquitetura (G1/G2 restringem `parsing/`/
`extraction/` de importar `mcp/`, não o inverso; `mcp/` é a camada mais
externa e já depende de `graph/`, então depender também de
`extraction/`/`parsing/` não introduz nenhum ciclo). Nenhuma execução de
código do agente acontece — `jsx_source` é só texto passado por regex/
parsing determinístico, o mesmíssimo caminho que já processa HTML/JS não
confiável de protótipos hoje.

## Fora de escopo

- Resolver classes CSS customizadas/cores Tailwind para o candidato —
  exigiria recarregar e reprocessar o HTML original do protótipo a cada
  chamada da tool (custo e complexidade desproporcionais ao valor,
  documentado como limitação em vez de resolvido às pressas).
- Comparação de `props` — `jsx_source` é a expressão JSX, não a assinatura
  da função; props declaradas vêm de `extract_props_from_function_signature`
  sobre a assinatura, que o agente não está enviando neste fluxo.
- Comparação exata de valor de estilo quando a spec original já armazena
  uma expressão não resolvida (ex. `color: positive ? C.green : C.red`) —
  isso é uma característica da extração de base (ternárias não resolvidas
  a literal), não algo que este change deveria mascarar ou "consertar" por
  fora.
