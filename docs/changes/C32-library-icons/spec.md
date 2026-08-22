# Spec C32 — Referências externas permanentemente não resolvidas (re-escopado de "ícones de biblioteca")

## Contexto

Oitava de 9 changes (C25–C33) motivada pela auditoria técnica completa do
pipeline (ver C25/spec.md). O escopo original planejado era "captura de
ícones de biblioteca (lucide-react/heroicons) via heurística de nome" —
investigado durante a implementação e **re-escopado** com uma justificativa
concreta (ver "Investigação e re-escopo" abaixo), seguindo a mesma
disciplina que C23/C24 já aplicaram a outras ideias sem evidência
suficiente.

## Investigação e re-escopo

O plano original propunha: tag JSX PascalCase self-closing sem definição
própria no bundle + nome batendo um padrão conhecido de biblioteca de
ícones → node `Icon` com `name`/`source`. Ao investigar o caminho de dados
real, dois problemas tornaram esse escopo insustentável:

1. **Distinguir "é um ícone" de "é qualquer outro componente externo" a
   partir só do nome é não-confiável.** `<ChevronRight />` parece ícone;
   `<DataGrid />` ou `<PaymentFlowSelector />` (nomes reais do protótipo de
   referência) são claramente componentes externos não-ícone. Uma lista
   curada de nomes conhecidos de lucide-react/heroicons seria frágil,
   incompleta, e overfit a duas bibliotecas específicas — exatamente o tipo
   de heurística especulativa que este projeto já rejeitou antes (ver
   `dark:`/`sm:`/`md:`/`lg:` em C29, `styled-components` em C24).

2. **Um problema mais grave e com evidência direta foi encontrado no
   caminho.** Lendo `GraphWriter.flush_pending_contains()`
   (`graph/writer.py`) para entender onde a captura de ícone se encaixaria:
   um `child_ref` de componente (`CONTAINS`) que nunca corresponde a um
   componente extraído localmente — o caso comum de um import de
   biblioteca, ícone ou não — fica em `_pending_contains` para sempre.
   `flush_pending_contains()` roda exatamente uma vez, loga em `debug` que
   a aresta continua pendente, e **descarta**. Diferente de uma referência
   de Screen/Section a um componente indefinido (que já ganha um node
   "shell" via `_ensure_component_exists`, com `occurrence=UNRESOLVED`), uma
   referência de Component→Component nessa situação **nunca vira node
   nenhum** — pior que "child_ref genérico sem informação visual" (a
   descrição original do achado da auditoria): é invisível por completo no
   grafo persistido. `get_component_children` do pai não retorna nada para
   esse filho.

## Problema identificado (revisado)

### P1 — Referência de componente permanentemente externa desaparece do grafo

Confirmado por leitura direta de código e depois por rebuild real: no
protótipo de referência (`iPede Manager v21.2.html`), **15 referências**
que hoje desapareciam silenciosamente do CONTAINS (`KField`, `KSel`,
`KTextInput`, `MenuItem`, `PromoIcon`, entre outras) passam a existir como
node `Component` com `occurrence=UNRESOLVED` depois do fix — visíveis por
nome, mesmo sem markup/props conhecidos.

## Solução proposta

| Task | Problema | Camada |
|---|---|---|
| T70 | P1 | `graph/writer.py` (`flush_pending_contains`) |

**T70** — `flush_pending_contains()` passa a chamar
`_ensure_component_exists(child)` (mesmo mecanismo já usado para
referências de Screen/Section a componente indefinido) para todo `child`
ainda não resolvido no momento da chamada — momento em que isso é
definitivo, não "talvez na próxima vez": a função só é chamada depois que
todo `write_component()` do build já rodou, então nada mais poderia
resolver esse nome depois. A aresta CONTAINS é então escrita normalmente.
Comportamento preservado: dedup de arestas (`_contains_keys`) já garantia
idempotência independente desse fix; chamar a função mais de uma vez
continua seguro (a segunda chamada só encontra um conjunto pendente vazio).

## Cobertura de testes exigida

- `TestUnresolvedChildBecomesShell` (5 casos): aresta é escrita para um
  filho nunca definido em lugar nenhum; o shell criado tem
  `occurrence=UNRESOLVED`; `get_component_children` do pai retorna o nome
  externo; `get_stats()["unresolved_components"]` reflete a contagem;
  regressão — um filho realmente definido localmente não é afetado (guard
  específico contra o fix vazar para o caminho normal).
- Regressão: `test_flush_pending_contains_is_idempotent` (já existente)
  continua passando — chamar a função duas vezes não duplica arestas.

Suíte completa (`pytest tests/unit/ -q`, `pytest tests/integration/ -q`) sem
regressão e guardrails (`pytest tests/test_architecture_guardrails.py -q`)
intactas; rebuild real contra `iPede Manager v21.2.html` (DB descartável em
`/tmp`) reportado no `plan.md`.

## Segurança

Nenhuma nova fronteira de I/O — o fix opera inteiramente sobre nomes já
extraídos do arquivo local do protótipo.

## Fora de escopo

- Classificação semântica "isto é um ícone" — ver "Investigação e
  re-escopo" acima. Um node `Component` com `occurrence=UNRESOLVED` e
  `jsx_snippet=''` já sinaliza "definição externa, natureza desconhecida"
  de forma honesta, sem fingir saber mais do que o grafo realmente sabe.
- Captura de markup/props real de bibliotecas de ícones — exigiria acesso
  ao pacote npm real (fora do que este pipeline processa: só o HTML/JS já
  bundlado do protótipo).
- Diferenciar "external de biblioteca" de "bug real de nome digitado
  errado no protótipo" — ambos produzem a mesma forma de dado
  (`occurrence=UNRESOLVED`), e não há sinal disponível no bundle para
  distingui-los de forma confiável.
