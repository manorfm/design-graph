# T43 — Classificação de Overlay para editores full-page não roteados

**Arquivos:** `src/design_graph/extraction/screen_extractor.py`,
`src/design_graph/pipeline/coordinator.py`
**Depende de:** T42 (CONTAINS precisa estar completo para a árvore do
overlay valer o custo de resposta)
**Status:** `[x] done`

## Responsabilidade

`ScreenIdentity.classify()` (C17) exclui deliberadamente nomes terminados
em `Panel/Tab/List/Section/Modal` da classificação de Screen roteável —
decisão testada e intencional, **não reaberta por esta task**. Isso deixa
componentes como `ItemEditorV6` (raiz de editor full-page com abas
condicionais) inalcançáveis por `list_screens`/`get_screen_full`, mesmo
sendo o tipo de tela que um agente mais precisa para fechar paridade
visual. Esta task reconhece esse padrão por **estrutura**, nunca por nome.

## Nota de implementação — desenho bem mais enxuto que o previsto na spec

Duas suposições da spec original caíram ao ler o código antes de escrever
qualquer teste:

1. `ScreenRole`/`ScreenIdentity` vivem em `extraction/screen_extractor.py`
   (não em `core/models.py`, como a spec assumia por analogia errada com
   outros enums do C14) — e **nada persiste um "papel" no grafo hoje**:
   `ExtractedScreen` não tem campo de role. `ScreenRole.OVERLAY` seria um
   membro de enum sem nenhum consumidor — a exata "abstração sem
   necessidade real" que este change inteiro pede para evitar. Descartado.
2. `GraphReader.get_screen_full` (Q5) já monta o fecho **transitivo** de
   CONTAINS (`(:Screen)-[:USES_COMPONENT]->(:Component)-[:CONTAINS*0..3]->(:Component)`)
   a partir dos filhos diretos do Screen. Uma vez que `ItemEditorV6` tem
   `BasicTab` no próprio `component_refs` — já capturado sobre o JSX bruto,
   sem precisar de marcador nem sanitização — a árvore inteira (`BasicTab`
   e, graças ao T42, os filhos dele) sai assemblada de graça. Nenhuma
   resolução especial de `{[conditional:X]}` foi necessária.

Resultado: nenhuma mudança em `core/models.py`, `graph/schema.py`,
`graph/writer.py`, `graph/reader.py` ou `mcp/tools.py`. A task inteira
ficou contida em `screen_extractor.py` (a classificação) e
`pipeline/coordinator.py` (repassar o corpo do boundary pra classificação).

## Critério de aceite

- `screen_extractor._is_overlay_shell(body)`: pré-filtro barato
  (`_RE_TAB_TAG_HINT`, contagem de tags `<...Tab` sem rodar o sanitizador)
  antes de chamar `sanitize_jsx` e contar marcadores
  `{[conditional:*Tab]}`/`{[either:*Tab...]}` — 2+ conta como overlay.
  Nenhum código novo duplica a lógica de colapso do sanitizador.
- `is_screen(name: str, body: str = "")` — assinatura estendida,
  retrocompatível (todo chamador com só o nome continua na classificação
  pura por sufixo). Decide por `ScreenIdentity.classify(name).is_top_level
  or _is_overlay_shell(body)` — **a tabela de sufixos do C17 não foi
  tocada**.
- `test_is_screen_classification` (suíte já existente, casos
  `("ProfileModal", False)`, `("BillList", False)` etc., todos chamados
  sem `body`) continua passando **sem nenhuma alteração no teste** — prova
  de não-regressão por construção, não por reafirmação.
- `extract_screens` e `pipeline/coordinator.py` (`screen_bounds`/
  `comp_bounds`) passam o corpo do boundary para `is_screen`.
- Teste ponta a ponta (`test_overlay_shell_excluded_from_extracted_components`,
  via `coordinator.extract_react`) prova as duas metades do resultado: o
  boundary aparece em `screens`, **e** não aparece mais em `comps` — a
  mesma regra "screen boundary nunca também é Component" que já vale para
  toda Screen do sistema.
- Suíte completa (`pytest tests/unit/ -q`) sem regressão; guardrails
  G1–G11 intactas.
- Rebuild real contra `iPede Manager v15.1.html`: Screens 16→17 (um
  overlay real do protótipo passou a ser classificado), CONTAINS 262→343.
  `design-graph validate` sem erros/avisos.

## Consequência aceita, não regressão

Um boundary que vira Screen para de passar por `extract_component` —
mesma regra já válida para toda Screen do sistema (`coordinator.py`: "a
screen boundary must never also be extracted as a component"). O overlay
perde a própria spec de Component (suas próprias interações de
hover/foco, texts, props, se tivesse) em troca de ganhar a árvore inteira
assemblada via `get_screen_full` — a troca que este task existe para
fazer. Rebuild real: `interactions` 72→67, `texts` 1369→1348,
`component_props` 584→576 — perda pontual atribuível a essa troca, não a
um bug (ver tabela completa em `plan.md` → Validação end-to-end).

## Fora de escopo

- Reabrir/ampliar `ScreenIdentity.classify()` para reincluir os sufixos
  excluídos no C17 — permanece intocado.
- Resolver mais de uma aba por chamada de `get_screen_full`, ou qualquer
  lógica de "aba default" — desnecessário: o fecho transitivo de CONTAINS
  já inclui todas as abas referenciadas no corpo do overlay, não só a
  primeira.
- "Raiz não aninhada como filho de nenhum outro componente" como critério
  formal — a spec original cogitava essa checagem; a densidade de
  marcadores de aba condicional (2+) já é um sinal suficientemente forte
  na prática (confirmado pelo rebuild real) sem precisar de análise de
  aninhamento entre boundaries.
- Paginação da árvore do overlay — não necessária: o custo por resposta
  não mudou (mesma query `get_screen_full` já usada por toda Screen,
  nenhum caminho novo).
