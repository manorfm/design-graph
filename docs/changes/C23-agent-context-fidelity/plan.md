# Plan C23 — Fidelidade de contexto do MCP para agentes de IA

## Objetivo

Fechar os sete gaps documentados em `spec.md` (P1–P8) sem regredir nenhum
comportamento coberto por C09–C22, mantendo as guardrails de arquitetura
(G1–G11) e sem expandir escopo para as duas frentes explicitamente adiadas
(`compare_html`, reabertura do classificador de Screen do C17).

## Critério de aceite

```bash
# por task, ver "Critério de aceite" no respectivo TNN-*.md — todos devem
# passar isoladamente antes de seguir para a próxima task da mesma iteração

pytest tests/unit/ -q                         # suíte completa sem regressão
pytest tests/test_architecture_guardrails.py -q   # G1–G11 intactas
design-graph "iPede Manager v15.1.html" --force --db /tmp/c23-rebuild.db
design-graph validate --db /tmp/c23-rebuild.db
```

Rebuild real sempre contra `/tmp` (ou outro caminho descartável) — nunca
contra a DB de produção do repositório.

## Ordem de implementação recomendada

```
Iteração 1 (paralela — sem dependência entre si):
  T37  mcp/search.py                         (P1)
  T38  extraction/jsx_sanitizer.py            (P2, P3)
  T39  extraction/plain_html_component_extractor.py (P4)
  T40  parsing/token_extractor.py             (P5)

Iteração 2:
  T41  core/models.py + mcp/tools.py          (P6) — depende de T38
       (vocabulário de marcadores usado por JsxSnippet.was_sanitized
       deve refletir o formato que T38 deixa)
  T42  extraction/ (spike + fix)              (P7) — independente,
       mas deve concluir antes de T43

Iteração 3:
  T43  core/ + extraction/ + graph/ + mcp/    (P8) — depende de T42
       (assembler de overlay precisa de CONTAINS completo pra valer a pena)
```

Cada task é releasável isoladamente — nenhuma exige que outra tenha sido
mesclada antes de ir para produção, exceto as dependências marcadas acima.

## Sequência por task

### T37 — Tokenização de busca (P1)

**RED:** `test_multi_word_query_finds_component_matching_all_terms` — dois
nomes reais do grafo de teste, um casando com o primeiro termo e outro com
o segundo; query com os dois termos deve retornar ambos, ranqueados por
quantos termos cada um cobre. Prova que o comportamento atual (comparação
de string inteira) devolve zero resultados para esse caso.

**GREEN:** `expand_query` passa a tokenizar por espaço (mantendo a
expansão de alias por termo individual, não mais sobre a frase inteira);
`score_match` ganha uma variante de cobertura (fração de termos da query
encontrados no nome, cada termo ainda pontuado 0/40/60/80/100 como hoje) e
o resultado final ordena por essa cobertura antes do score bruto. Nenhuma
regex nova — tokenização e comparação continuam por operações de string
puras (ver Segurança em `spec.md`).

**Regressão:** todas as queries de uma palavra usadas pelos testes
existentes de `search.py` continuam com o mesmo score.

### T38 — Ternário no colapso de estilo + nome do handler preservado (P2, P3)

**RED (P2):** `test_ternary_style_block_preserves_both_branches` —
`style={{ padding: cond ? '4px 8px' : '6px 10px', ... }}` acima do limiar
de colapso; o texto colapsado hoje corta em `padding: cond ?,`, perdendo
os dois ramos.

**GREEN (P2):** `_collapse_long_style_blocks` troca a extração de
propriedade por um scan que localiza o `?`/`:` de um ternário via
`find_matching_delimiter`-style (mesma técnica balanceada de C13/C21) antes
de decidir onde uma propriedade termina, preservando os dois ramos no
preview em vez de truncar no primeiro token.

**RED (P3):** `test_long_handler_collapse_preserves_prop_name` —
`onChange={e => { ...corpo longo... }}` deve colapsar para algo como
`onChange={.[handler]}` (ou equivalente que preserve o nome), nunca
`on[handler]` genérico.

**GREEN (P3):** `RE_LONG_EVENT_HANDLER` (ou o `.sub()` que a usa) passa a
capturar o nome do evento como grupo e reinjetá-lo no marcador de saída.

**Regressão:** casos já cobertos por C21 (proteção de markup cru) e C22
(ícones) continuam intocados — nenhum dos dois mexe em ícone/lista/either,
só em bloco de estilo e handler.

### T39 — Estilo por profundidade de elemento (P4) — `[x] done`

**RED:** `test_nested_child_style_is_not_attributed_to_the_component` — um
`<button>` raiz com `display`/`padding` próprios e um `<span class="dot">`
filho com `width`/`height`/`border-radius` — as propriedades do filho não
devem aparecer no `styles` do componente. Caso real do `Chip` (dot 7px),
reduzido ao mínimo em `tests/unit/extraction/test_plain_html_component_extractor.py`
(não dependeu de promover fixture de `audit/` — snippet inline bastou).

**GREEN:** implementado mais simples do que a spec original previa —
`_extract_inline_styles` para de ler depois do primeiro `style="..."` do
snippet (o elemento raiz); nenhum estilo de descendente chega a virar
`StyleEntry`. Sem campo novo em `StyleEntry`, sem mudança em
`mcp/tools.py` — ver nota de implementação em `T39-*.md`.

**Regressão:** `test_root_only_styles_...` roda também com um componente
que só tem estilo na raiz (nenhum filho estilizado) — tabela idêntica à de
hoje.

### T40 — Normalização de rótulo de token malformado (P5)

**RED:** `test_radius_with_trailing_punctuation_is_discarded_not_leaked` —
valor capturado como `"8,"` não deve produzir o token `radius_8,`; deve
ser descartado antes de contar (não aparece na lista de tokens de forma
alguma, já que não é uma correção de valor confiável — é dado malformado).
Testes irmãos para spacing/font-size/font-weight/shadow, cada um provando
que a mesma classe de fallback sujo não existe nessas categorias (podem já
passar hoje — se passarem, viram teste de regressão, não RED).

**GREEN:** `_normalise_radius` (e as normalizações irmãs, se o RED
encontrar o mesmo bug nelas) passa a ser o portão real: valor que não
sobrevive como numérico limpo (dígitos + `px`/`%` opcional, sem sobra) é
descartado do `Counter` antes de qualquer rótulo ser derivado — não chega
mais ao fallback `v[:12]`.

### T41 — Honestidade de `get_full_jsx` (P6) — `[x] done`

*Depende de T38* — o vocabulário de marcadores que `JsxSnippet` reconhece
deve incluir o formato que T38 deixa para handler/estilo colapsado.

**RED:** `test_get_full_jsx_flags_sanitized_snippet` — snippet contendo
`{[conditional:X]}` (ou qualquer outro marcador do vocabulário) devolvido
por `get_full_jsx` deve conter um aviso explícito, não o cabeçalho
incondicional `"# JSX completo"`. `test_get_full_jsx_clean_snippet_stays_unflagged`
— snippet sem nenhum marcador continua com o cabeçalho atual, sem aviso
falso-positivo.

**GREEN:** `JsxSnippet(str)` em `core/models.py` com `.was_sanitized`
(regex de detecção dos marcadores conhecidos, não de conteúdo arbitrário)
e `.markers_found`; `ToolDispatcher.get_full_jsx` em `mcp/tools.py` decide
o cabeçalho e acrescenta o aviso a partir desse valor, em vez de montar a
string incondicionalmente.

### T42 — Spike + fix de completude do CONTAINS (P7) — `[x] done`

**RED (spike):** `test_namespaced_child_tag_is_captured` — fixture mínima
inline com `<K.Card>`/`<K.Field>`/`<K.Segmented>`/`<K.Chip>`. Prova a
subcontagem atual.

**Investigação:** a hipótese líder da `spec.md` (CONTAINS computado sobre
JSX pós-sanitização) foi **refutada** — `component_extractor.py` já
escaneia o `window` bruto (pré-sanitização), não o `jsx_snippet`. Causa
real: `RE_JSX_TAG` (`core/patterns.py`) exigia o nome do componente logo
depois de `<`, sem suportar tag JSX namespaced (`<K.Chip`, member
expression) — padrão de autoria do design system do protótipo confirmado
no HTML ao vivo da investigação original. `RE_COMP_REF` (heurística por
sufixo) também não cobre esses nomes: eles OU não terminam em nenhum
sufixo conhecido OU (`Card`, `Btn`, `Pill`) são eles mesmos um sufixo
inteiro, e a regex exige prefixo antes do sufixo. Documentado com o
detalhe completo em `T42-*.md`.

**GREEN:** `RE_JSX_TAG` ganhou um prefixo de namespace opcional e não
capturado (`(?:[A-Za-z_$][\w$]*\.)*`) antes do nome PascalCase — captura
continua sendo só o nome do componente (`Chip`, nunca `K.Chip`).
`test_namespace_prefix_itself_is_not_captured_as_a_child` prova que o
namespace em si nunca vira `child_ref`; `test_react_internals_not_in_child_refs`
(regressão, `<React.Fragment>`) continua verde — agora filtrado por
`REACT_INTERNALS`, não mais por o regex simplesmente nunca casar.

### T43 — Classificação de Overlay para editores full-page (P8) — `[x] done`

*Depende de T42* — confirmado necessário: sem CONTAINS completo, o
overlay assembla uma árvore capenga.

**RED:** `test_two_or_more_conditional_tabs_is_a_screen`
(`screen_extractor`) + `test_overlay_shell_excluded_from_extracted_components`
(`coordinator`, ponta a ponta) — um componente sem nenhum sufixo de
`ScreenIdentity` (ex. `ItemEditorV6`), cujo corpo alterna 2+ filhos
`*Tab` por `&&` condicional, deve virar Screen, não Component.

**Investigação que mudou o desenho:** duas suposições da spec original
caíram ao ler o código:

1. `ScreenRole`/`ScreenIdentity` vivem em `extraction/screen_extractor.py`,
   não em `core/models.py` — e `ExtractedScreen` **não tem campo de
   papel/role algum**. Um "papel" nunca é persistido no grafo hoje; ele só
   decide, em tempo de extração, se um boundary vira Screen. Não havia
   nada em `graph/schema.py`/`graph/writer.py` para estender — `ScreenRole.OVERLAY`
   seria um membro sem nenhum consumidor.
2. `reader.get_screen_full` (Q5) já monta o fecho **transitivo** de
   CONTAINS (`USES_COMPONENT->CONTAINS*0..3`) a partir dos filhos diretos
   do Screen. Nenhuma resolução especial de `{[conditional:X]}` era
   necessária: uma vez que `ItemEditorV6` tem `BasicTab` no seu próprio
   `component_refs` (já capturado por `_collect_component_refs` sobre o
   JSX bruto, sem precisar de sanitização), a árvore inteira — `BasicTab`
   e (graças ao T42) os filhos dele — já sai assemblada de graça.

**GREEN (bem mais enxuto que o previsto):** `screen_extractor.py` ganhou
`_is_overlay_shell(body)` — pré-filtro barato (`_RE_TAB_TAG_HINT`) antes
de rodar `sanitize_jsx` e contar marcadores `{[conditional:*Tab]}`/
`{[either:*Tab...]}` (limiar: 2+). `is_screen(name, body="")` passou a
aceitar o corpo opcional e decide por `ScreenIdentity.classify(name).is_top_level
or _is_overlay_shell(body)` — **sem tocar a tabela de sufixos do C17**.
`extract_screens` e `pipeline/coordinator.py` (`screen_bounds`/`comp_bounds`)
passaram a fornecer o corpo. Nenhuma mudança em `core/models.py`,
`graph/schema.py`, `graph/writer.py`, `graph/reader.py` ou `mcp/tools.py`
foi necessária.

**Consequência aceita, não regressão:** um boundary que vira Screen para
de passar por `extract_component` — mesma regra já válida para toda
Screen do sistema ("a screen boundary nunca também é extraída como
Component", `coordinator.py`). `ItemEditorV6` perde a própria spec de
Component (suas próprias interações de hover, se tivesse) em troca de
ganhar a árvore inteira assemblada via `get_screen_full` — a troca que
este task existe para fazer. Rebuild real confirmou o efeito (ver tabela
abaixo: `interactions` caiu 72→67, atribuível a essa perda pontual, não a
um bug).

## Validação end-to-end

Rebuild real contra `iPede Manager v15.1.html`, DB descartável em `/tmp`
(nunca a DB de produção do repo), comparado via `git stash` do diff
completo do C23 (baseline = HEAD antes de qualquer task; pós-C23 = as sete
tasks juntas, já que a implementação foi rápida o suficiente para não
justificar três rebuilds intermediários separados):

```
Métrica          | baseline (pré-C23) | pós-C23 (T37–T43) | leitura
------------------|---------------------|--------------------|---------
Screens           | 16                  | 17                 | +1 — overlay real do protótipo agora classificado (T43)
Components        | 173                 | 172                | -1 — o mesmo boundary não é mais Component+Screen ao mesmo tempo (esperado, ver T43)
CONTAINS edges     | 262                 | 343                | +81 — tags namespaced (`<K.Chip`) agora visíveis (T42) + o novo Screen
Sections           | 77                  | 78                 | +1 — seções do overlay recém-incluído
Section styles     | 614                 | 635                | +21
Tokens             | 76                  | 79                 | +3
Styles             | 3856                | 3832               | -24 — estilo de descendente deixou de vazar pra raiz (T39)
Interactions        | 72                  | 67                 | -5 — perda pontual aceita (T43): o boundary que virou Screen não passa mais por extract_component, então não tem mais interações próprias extraídas — mesma regra de toda Screen do sistema
Texts              | 1369                | 1348               | -21 — mesma causa (Screen não extrai texts próprios como Component extraía)
Component props    | 584                 | 576                | -8 — idem
```

`design-graph validate --db <pós-C23>`: `status=ok errors=0 warnings=0`.
Nenhum token com rótulo malformado (`radius_\d+,` ou equivalente) na saída
de `get_tokens` do banco reconstruído.

Preencher os valores reais na hora da implementação — esta tabela é o
molde, não o resultado.
