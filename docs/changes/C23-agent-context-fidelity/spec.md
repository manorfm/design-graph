# Spec C23 — Fidelidade de contexto do MCP para agentes de IA

## Contexto

Investigação disparada por uma auditoria manual de paridade visual entre um
protótipo (`ipede_manager_v21.1`) e a implementação real (`iPede Manager`,
aba **Básico** do editor de item). Evidência bruta em `audit/` (não
versionado, uso local): `audit/mcp-gap-analysis-item-basic-tab.md` documenta
4 tentativas de um modelo alinhando a mesma tela via MCP sem fechar o gap;
`audit/prototipo.png`/`audit/sistema.png` são os prints comparados;
`audit/fixtures/*.html` é o DOM real capturado por browser MCP como
contraprova.

Este change não mexe no protótipo nem na app iPede — mexe **apenas** no
`design-graph` (o servidor MCP e o pipeline de extração que o alimenta),
que é este repositório. Cada problema abaixo foi confirmado lendo o código-
fonte real (`src/design_graph/`), não só inferido do relato do modelo — a
seção **Problemas** cita arquivo e função de origem para cada um.

## Problemas identificados

### P1 — `search` não tokeniza consultas de múltiplas palavras

`mcp/search.py::expand_query` trata a query inteira como **um único termo**
de match (mais expansões de alias sobre essa mesma string inteira). Uma
busca como `"ItemEditor BasicTab ItemEditorV6"` é comparada, ao pé da
letra, como se `"itemeditor basictab itemeditorv6"` precisasse ser
substring literal de um nome — o que nunca acontece. O sintoma relatado
como "índice instável" no documento de auditoria é, na verdade, ausência
de tokenização: sessões diferentes tentaram queries diferentes (uma
palavra vs. frase composta) e naturalmente tiveram resultados diferentes.

### P2 — Colapso de bloco de estilo corta ternários no meio

`extraction/jsx_sanitizer.py::_collapse_long_style_blocks` reduz qualquer
`style={{...}}` acima de 400 caracteres a "6 propriedades + `...`" usando
uma extração de propriedade que não entende ternário
(`padding: cond ? A : B` vira `padding: cond ?,` — o valor verdadeiro nunca
aparece). É a causa direta do modelo "chutar" a cor de estado selecionado
do componente `Segmented` no caso relatado.

### P3 — Colapso de handler perde qual evento era

`jsx_sanitizer.py::sanitize_jsx` substitui o corpo de um handler longo por
`on[handler]`, apagando o nome da prop (`onChange`, `onClick`, `onBlur`).
O JSX sanitizado fica ambíguo sobre qual interação está sendo descrita.

### P4 — Estilo de elemento descendente é atribuído ao componente raiz

`extraction/plain_html_component_extractor.py::_extract_inline_styles`
varre todo `style="..."` dentro do snippet do componente em ordem de
documento e deduplica por propriedade, sem nenhuma noção de **qual
elemento** (raiz vs. filho aninhado) é dono de cada propriedade. No caso
relatado, o `<span class="dot">` de 7px interno ao `Chip` teve
`width`/`height`/`border-radius`/`background` promovidos à tabela "Estilos
— default" do `Chip` como se fossem do `<button>` raiz — levando o modelo
a concluir, errado, que o componente "é uma bolinha".

### P5 — Tokens de design com rótulo corrompido

`parsing/token_extractor.py::_radius_label` cai num fallback
(`f"radius_{v[:12]}"`) sempre que `float(v)` falha — e não valida que `v`
seja um valor numérico limpo antes de contar a ocorrência. Um valor
capturado com vírgula sobrando (ex. de uma definição de token JS tipo
`sm: 8,`) vira o rótulo `radius_8,`, publicado como se fosse um nome de
categoria válido. O mesmo formato de fallback aparece nas funções de
rótulo irmãs (spacing, font-size, font-weight, shadow) e não foi auditado
uma a uma.

### P6 — `get_full_jsx` rotula como "completo" um snippet já sanitizado

`mcp/tools.py::ToolDispatcher.get_full_jsx` devolve `reader.get_full_jsx`
sob o cabeçalho fixo `"# JSX completo"`, sem checar se o texto contém
marcadores deixados por `sanitize_jsx` (`on[handler]`, `.[fn]`,
`{[list:…]}`, `{[conditional:…]}`, `{[either:…]}`, `{...}`). O corte não
acontece na resposta do tool (não há `CappedJsx` aqui — diferente de
`get_screen_full`/`get_component_spec`) — acontece na **extração**, e o
tool não tem como avisar disso porque nunca verifica. Resultado observado:
o modelo trata a saída como definitiva e para de investigar.

### P7 — CONTAINS incompleto para componentes com abas/condicionais

`get_component_children('BasicTab')` devolve 4 filhos
(`IconBtn, NumInput, SwitchRow, TextInput`) contra pelo menos 12 usados de
fato no JSX real (`Card, Field, Segmented, Chip, Pill, TextArea, Sel, Btn`
entre outros). Causa confirmada no spike de T42:
`patterns.py::RE_JSX_TAG` exigia o nome do componente logo após `<`, sem
suportar tag JSX namespaced (`<K.Chip`, um member expression) — o padrão
de autoria do design system do protótipo, confirmado no HTML ao vivo da
investigação original. `RE_COMP_REF` (heurística por sufixo conhecido)
também não cobre esses nomes: nenhum termina em um sufixo da lista, ou
(`Card`, `Btn`, `Pill`) o nome inteiro É um sufixo da lista, e a regex
exige um prefixo antes dele. A hipótese original desta spec (CONTAINS
computado sobre JSX pós-sanitização) foi investigada e **refutada** — a
extração de filhos já rodava sobre o fonte bruto, não sobre o snippet
sanitizado.

### P8 — Editores/overlays full-page não são alcançáveis como tela

`ScreenIdentity.classify()` (`core/models.py`, decisão do C17) exclui
deliberadamente nomes terminados em `Panel/Tab/List/Section/Modal` da
classificação de Screen — comportamento testado e intencional, não um
esquecimento. Isso deixa componentes como `ItemEditorV6` (raiz de um
editor full-page com abas condicionais) fora de `list_screens` e de
`get_screen_full`, mesmo sendo exatamente o tipo de tela que um agente
pede para fechar paridade visual. Sintoma agravante: o JSX raiz desse tipo
de componente troca o corpo de cada aba por
`{[conditional:BasicTab]}` — ver `<K.Chip` real dentro da aba nunca é
alcançado a partir da tela inteira, só chamando a aba isoladamente.

## Solução proposta

Sete frentes independentes o suficiente para paralelizar, descritas em
detalhe cada uma no seu próprio `TNN-*.md` (ver `plan.md` para sequência e
ordem recomendada):

| Task | Problema(s) | Camada afetada |
|---|---|---|
| T37 | P1 | `mcp/` |
| T38 | P2, P3 | `extraction/` |
| T39 | P4 | `extraction/` |
| T40 | P5 | `parsing/` |
| T41 | P6 | `core/` + `mcp/` |
| T42 | P7 | `core/` (spike + fix — causa achada em `patterns.py`, não em `extraction/`) |
| T43 | P8 | `extraction/` (só — ver nota de implementação em T43) |

Nenhuma task reabre P8 tocando na exclusão de sufixos do C17 — T43 cria um
caminho de classificação **adicional**, não substitui o existente (ver
Fora de escopo).

## Entidades ricas e value objects

Este change segue o padrão já estabelecido no C14
(`EntityId`, `_StrEnum`, `PropDefault`) em vez de introduzir uma
convenção nova:

- **`JsxSnippet`** (novo, `core/models.py`) — `class JsxSnippet(str)`
  encapsulando um trecho de JSX já sanitizado. Expõe `.was_sanitized`
  (bool, computado por presença de qualquer marcador conhecido) e
  `.markers_found` (lista dos tipos de marcador presentes). Substitui o
  `f"# JSX completo"` incondicional de `get_full_jsx` por uma decisão
  informada pelo próprio valor — mesmo espírito de `CappedJsx` (T27,
  C14/C18): o fato de "isto está incompleto" mora no valor, não é
  recalculado ad-hoc no site de renderização.
- **`RadiusValue`/normalização em `TokenExtractor`** — em vez de um novo
  tipo, P5 se resolve tornando `_normalise_radius` (já existente) o único
  portão de entrada: valores que não sobrevivem a essa normalização como
  numéricos limpos são descartados **antes** de entrar no `Counter`, nunca
  depois. Não é value object novo — é fechar um portão que já existia mas
  não filtrava o suficiente.
- **`StyleEntry`** (já existe, C14) — a spec original cogitava estendê-lo
  com profundidade de elemento para resolver P4. Implementado sem tocar a
  entidade: `_extract_inline_styles` para de ler depois do primeiro
  `style="..."` do snippet, então nenhum estilo de descendente chega a
  virar `StyleEntry` — mesmo resultado, sem campo novo sem consumidor (ver
  nota de implementação em T39).
- **`ScreenRole`** — a spec original cogitava um membro `OVERLAY` novo.
  Investigado e descartado: `ScreenRole` vive em `extraction/screen_extractor.py`
  (não em `core/models.py`), e nenhum "papel" é persistido no grafo hoje —
  `ExtractedScreen` não tem campo de role. Um membro de enum sem nenhum
  consumidor seria a exata "abstração sem necessidade real" que este
  change pede para evitar. T43 classifica por estrutura sem introduzir
  nenhum tipo novo (ver nota de implementação em T43).

Nenhuma das mudanças acima introduz um novo padrão de modelagem — todas
reusam o vocabulário (`_StrEnum`, `EntityId`, classe `str` especializada
com propriedade computada) que o C14 já deixou estabelecido, exatamente
para que este change não vire uma segunda convenção paralela.

## Cobertura de testes exigida

Cada task segue TDD (RED → GREEN, ver `plan.md`) e deve, no mínimo:

- **P1/T37**: queries de 1, 2 e 3+ palavras contra nomes conhecidos;
  query cujos termos existem em nomes diferentes (nenhum nome tem os dois
  juntos) — deve encontrar ambos, ranqueados por cobertura; garantir que
  nenhum termo da query é compilado como regex (ver Segurança).
- **P2/T38**: `style={{}}` com ternário simples, ternário aninhado em
  template literal, e o caso real do `Segmented` (fixture de
  `audit/fixtures/` pode virar fixture de teste, ver Riscos); handler
  longo de cada tipo já coberto por `RE_LONG_EVENT_HANDLER` preservando o
  nome da prop no marcador resultante.
- **P4/T39**: componente com estilo só na raiz (baseline, sem regressão);
  componente com estilo em elemento aninhado e nenhum na raiz (garante que
  a tabela "default" não fica vazia por engano); caso real do `Chip`
  (dot 7px) não deve mais aparecer como estilo do componente.
- **P5/T40**: valor de radius limpo (regressão); valor com vírgula
  sobrando (não deve gerar `radius_8,`); mesma varredura repetida para
  spacing/font-size/font-weight/shadow — um teste por categoria provando
  que nenhuma delas tem o mesmo fallback sujo.
- **P6/T41**: snippet sem nenhum marcador → `was_sanitized is False`,
  cabeçalho continua "completo"; snippet com cada tipo de marcador →
  `was_sanitized is True`, aviso explícito no texto devolvido por
  `get_full_jsx`.
- **P7/T42**: teste de regressão fixando a contagem de filhos de
  `BasicTab` (ou componente equivalente na fixture de teste) antes/depois
  — o spike deve produzir pelo menos um teste RED que prova a
  subcontagem atual antes de qualquer fix ser proposto.
- **P8/T43**: `list_screens` passa a listar o overlay; `get_screen_full`
  no nome do overlay resolve a aba default por trás do primeiro
  `{[conditional:X]}`; **teste de não-regressão explícito** rodando os
  casos parametrizados existentes de `ScreenIdentity.classify` (os mesmos
  `("ProfileModal", False)`, `("BillList", False)` do C17) para provar que
  a exclusão de sufixos continua intacta.

Além disso, ao final de cada task: suíte completa (`pytest tests/unit/ -q`)
sem regressão, guardrails de arquitetura (`pytest
tests/test_architecture_guardrails.py -q`) intactas, e rebuild real contra
um prototype de referência com stats antes/depois reportados no `plan.md`
(mesmo formato usado em C09–C22) — nunca contra a DB de produção.

## Segurança

- **Sem regex compilada a partir de entrada do usuário.** T37 tokeniza a
  query por espaço e compara por `in`/igualdade de string — nunca
  `re.compile(query)`. Uma consulta MCP vem de um agente de IA, não de um
  usuário final autenticado, mas ainda assim é entrada externa ao processo
  do servidor; compilar regex a partir dela abriria a porta para ReDoS.
- **Escaneamento balanceado, não regex gananciosa, em T38/T39.** Qualquer
  parsing novo de ternário/bloco de estilo reusa
  `parsing/js_parser.find_matching_delimiter` (scanner O(n), já usado por
  C13/C21) em vez de uma regex nova com grupos aninhados — mesma decisão
  já documentada no C13 como mitigação de custo quadrático.
  T42 (CONTAINS) e T43 (classificação de overlay), se precisarem de
  varredura adicional, seguem a mesma regra.
- **Nenhuma nova fronteira de I/O.** Todas as sete tasks leem dados já
  carregados pelo pipeline existente (HTML do protótipo, grafo Kuzu já
  aberto). Nenhuma aceita HTML/JSX vindo de fora do processo em tempo de
  chamada MCP — isso é o que distingue este change do `compare_html`
  cogitado na investigação original, propositalmente fora de escopo (ver
  abaixo).
- **G3/G5 preservados.** Nenhuma task escreve fora de `graph/writer.py`
  nem abre a DB fora de `read_only=True` no caminho MCP — nenhuma das
  sete tasks toca `graph/` (T43 acabou não precisando; ver nota de
  implementação em T43).
- **Constantes de limite, não loops abertos.** T40 (normalização) e T39
  (profundidade de elemento) devem usar as mesmas constantes `MAX_*`/caps
  já existentes em `core/constants.py` em vez de introduzir um novo limite
  mágico solto no meio da função.

## Performance / otimização de consumo de tokens

- T37 troca 1 comparação de substring por N (uma por termo) — N é limitado
  por `MAX_TOKENS_IN_SEARCH_QUERY_EXPANSION` (já existe); sem risco de
  regressão de custo perceptível dado o tamanho típico de uma query.
- T38/T39 não aumentam o tamanho médio do JSX devolvido — ao contrário,
  ao preservar o nome do handler e restringir estilos à raiz, o texto fica
  **mais correto por caractere gasto**, não maior. Nenhuma task desta
  spec deve aumentar o teto de caracteres (`CappedJsx` limits em
  `mcp/tools.py`) — o objetivo é gastar melhor o orçamento existente, não
  ampliá-lo.
- T41 adiciona no máximo uma linha de aviso condicional por chamada —
  custo desprezível, e evita a espiral de token cara descrita na
  auditoria original: 4 tentativas do mesmo agente realinhando a mesma
  aba porque não sabia que a resposta estava incompleta.
- T43 é a única com custo potencialmente maior por resposta
  (`get_screen_full` de um overlay monta uma árvore maior que uma aba
  isolada) — aceitável porque **substitui** múltiplas chamadas
  fragmentadas (`get_full_jsx` da tela + de cada aba + de cada
  subcomponente) por uma única chamada coerente; deve ser medido no
  rebuild real do `plan.md` (contagem de caracteres da resposta antes —
  via chamadas fragmentadas somadas — vs. depois).

## Arquitetura e boas práticas Python

- **Guardrails G1–G11 preservados por construção**, não só verificados no
  final: T37/T41 ficam em `mcp/`; T38/T39/T40/T42 ficam nas camadas que já
  ocupavam (`extraction/`, `parsing/`) sem novo import cruzado; T43 é a
  única que atravessa camadas (`core → extraction → graph → mcp`) e segue
  a direção de dependência já estabelecida (nunca o inverso).
- **TDD RED→GREEN obrigatório por task**, mesmo padrão de C09–C22 — cada
  `TNN-*.md` lista critério de aceite verificável, e `plan.md` sequencia
  as fases com o teste que prova o bug antes da correção.
- **Sem introdução de dependência nova.** Todas as sete tasks resolvem com
  a stdlib e os módulos internos já existentes (`re`, `parsing.js_parser`,
  `core.models`). Nenhuma justifica adicionar biblioteca externa.
- **YAGNI explícito**: T41 resolve por detecção em tempo de leitura
  (regex sobre o snippet já armazenado), não por uma coluna nova persistida
  no schema Kuzu — evita migração de grafo para um fato que é barato
  recomputar a cada leitura. T40 não introduz um `RadiusValue` value
  object novo quando apertar o portão de normalização existente já resolve
  o problema — um tipo novo ali seria abstração sem necessidade real.
- **Fail fast em vez de fallback silencioso.** P5 é, na raiz, um fallback
  (`f"radius_{v[:12]}"`) mascarando um dado malformado como se fosse
  válido. T40 substitui esse fallback por descarte explícito do valor —
  alinhado com o restante da base, que já prefere excluir um dado ruim a
  publicá-lo disfarçado (mesmo princípio usado pelas guardas de
  `_protected_markup_spans` no C21/C22: "deixar o texto bruto intocado em
  vez de adivinhar").

## Invariantes

- Nenhuma task muda o formato de saída Markdown dos tools MCP para casos
  já corretos hoje — só os casos com gap ganham texto adicional (aviso) ou
  valor corrigido; a estrutura de tabelas/headers existente não é
  redesenhada.
- IDs determinísticos (`EntityId`) continuam byte-compatíveis — nenhuma
  task desta spec adiciona ou reordena a seed usada em qualquer
  `.derive()`/`.literal()` existente.
- `sanitize_jsx` continua determinístico e idempotente — T38 corrige
  *como* ele colapsa um caso, não introduz não-determinismo.
- Rebuild do prototype de referência (`iPede Manager v15.1.html`, mesma
  referência de C09–C22) deve manter ou aumentar toda métrica de
  cobertura relatada nos changes anteriores — nenhuma pode regredir.

## Fora de escopo

- **`compare_html(name, liveHtml)`** (recomendação #10 da investigação
  original) — não é um ajuste a um tool existente, é uma capability nova:
  o servidor passaria a aceitar HTML/DOM vindo de fora do processo MCP em
  tempo de chamada, o que muda o perfil de segurança do servidor
  (superfície de entrada nova, potencial custo de parsing não limitado por
  nenhum dos caps hoje calibrados para HTML de protótipo já carregado).
  Merece spec e modelagem de ameaça própria — candidato a `C24`.
- **Reabrir a exclusão de sufixos do `ScreenIdentity.classify()` (C17)**
  — deliberadamente não tocado; T43 adiciona uma checagem estrutural
  independente em `is_screen()` em vez de ampliar a tabela de sufixos,
  exatamente para não reverter uma decisão já testada.
- **Índice de busca com prova formal de ausência** (distinguir "não
  indexado" de "não existe", P1) — a tokenização de T37 reduz a
  incidência do problema (queries corretas agora encontram o que existe),
  mas não elimina a ambiguidade residual de uma query que não encontra
  nada: pode ser ausência real ou termo mal escolhido. Resolver isso de
  verdade exigiria uma segunda fonte de verdade (ex. listagem exaustiva de
  nomes conhecidos) fora do escopo de uma correção de tokenização.
- **Lint/type-checking automatizado (`ruff`/`mypy`) no `pyproject.toml`**
  — o projeto não tem hoje. É uma melhoria de "boas práticas Python"
  válida, mas ortogonal ao tema desta spec (fidelidade de contexto para
  agentes) e não bloqueia nenhuma das sete tasks; fica como recomendação
  avulsa, não como task.

## Riscos e mitigação

| Risco | Mitigação |
|---|---|
| T39 (raiz vs. descendente) reduzir estilos capturados de componentes que hoje só têm dado útil vindo de um filho (ex. um wrapper puro sem estilo próprio) | Teste de regressão explícito com o inventário de componentes do prototype de referência antes/depois; se `any_styles` cair para um componente que antes tinha dado, tratar como achado a decidir caso a caso, não aplicar T39 cegamente a todos os component_type |
| T43 aumentar o custo de resposta de `get_screen_full` para overlays grandes | Materializado como esperado (resposta maior, substituindo várias chamadas fragmentadas por uma) — sem necessidade de paginação: o rebuild real não mostrou custo desproporcional, e a query usada é a mesma `get_screen_full` de qualquer Screen, não um caminho novo |
| T42 não confirmar a hipótese líder (JSX sanitizado por trás do gap de CONTAINS) | Materializado: a hipótese caiu, o spike achou a causa real (`RE_JSX_TAG` sem suporte a tag namespaced) e o fix seguiu a causa confirmada, não a hipótese original — ver T42-*.md |
| Fixtures de `audit/` (não versionadas) desaparecerem antes da implementação | Task correspondente deve promover o trecho mínimo necessário para uma fixture de teste versionada em `tests/fixtures/`, não depender de `audit/` sobreviver |

## Arquivos afetados (visão consolidada — detalhe por task em cada `TNN-*.md`)

| Arquivo | Tasks que tocam |
|---|---|
| `src/design_graph/mcp/search.py` | T37 |
| `src/design_graph/extraction/jsx_sanitizer.py` | T38 |
| `src/design_graph/core/patterns.py` (`RE_STYLE_PROP_PREVIEW`, `RE_LONG_EVENT_HANDLER`, `RE_JSX_TAG`) | T38, T42 |
| `src/design_graph/extraction/plain_html_component_extractor.py` | T39 (implementação final não tocou `core/models.py` — ver nota em T39) |
| `src/design_graph/core/models.py` | T41 (`JsxSnippet` + constantes de marcador) |
| `src/design_graph/parsing/token_extractor.py` | T40 |
| `src/design_graph/mcp/tools.py` | T41 |
| `src/design_graph/extraction/screen_extractor.py` | T43 |
| `src/design_graph/pipeline/coordinator.py` | T43 |
