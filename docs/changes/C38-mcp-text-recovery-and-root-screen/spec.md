# Spec C38 — Recuperação de texto sem corte + componente raiz como tela

## Contexto

Investigação disparada por dois relatos de outro agente (sessão externa,
projeto consumidor `toToggle`, monorepo `toToggles`), escritos depois de uma
reescrita de frontend contra o protótipo `toToggle v2.6.html` (já indexado
neste repositório, na raiz, para reprodução):
`design-graph-findings.md` e `design-graph-unreachable-components.md`. O
segundo documento já estava resolvido (reindexação anterior corrigiu os 6
componentes "JSX completo não disponível"). O primeiro tinha 3 achados ainda
abertos no momento desta investigação (Achado 1 já resolvido por C36 P4;
Achados 2, 3 e 5 reproduzidos e confirmados aqui antes da correção).

## Problemas confirmados

### P1 — Sem `get_full_jsx`-equivalente para textos (Achado 2)

C36 (T82) deu a estilos um escape hatch sem corte (`get_full_styles`), mas
textos continuaram só truncados na camada de apresentação
(`mcp/tools.py`, fatias `[:6]`/`[:8]`/`[:10]`) sem nenhuma forma de pedir a
lista completa — mesmo o reader já devolvendo tudo até o cap de extração
(`MAX_TEXTS_PER_COMPONENT = 30`). Reproduzido: `get_component_spec("App")`
mostrava 8 textos com `+N mais`; `validate_component_implementation` também
cortava sua própria lista de "textos ausentes" (`+5 mais`) sem ponteiro de
volta.

Achado colateral, mesma causa: mesmo onde `get_full_styles` já existe, nem
todo call site de truncamento de ESTILO apontava para ele — só o agrupamento
por seção (`_section_style_group_lines`) passava `recoverable_via`;
`get_screen_full`, `get_component_spec` e `get_component_full` deixavam a
notícia `+N mais` sem ponteiro em 4 dos 5 lugares onde estilos são
truncados.

### P2 — Componente raiz (`App`) nunca é uma "tela" (Achado 3, causa raiz)

`ScreenIdentity.classify` (extraction/screen_extractor.py) só reconhece
sufixos semânticos (`Page`/`Screen`/`Dashboard`/`View`/`Detail`) ou, por
estrutura, um shell de abas condicionais (C17). O componente raiz de um app
React — quase sempre chamado `App` por convenção (create-react-app, o
template React do Vite, e praticamente todo tutorial/boilerplate) — não
carrega nenhum desses sufixos, então nunca é classificado como tela. Isso
tornava `App` permanentemente ausente de `list_screens()` e
`get_section(screen="App", ...)` sempre "seção não encontrada" — mesmo
`App` sendo o componente que mais frequentemente precisa ser reconstruído
primeiro (é a casca inteira: sidebar, topbar, roteamento de view).
Confirmado no `toToggle v2.6.html` local: `App` ficava de fora das 9 telas
listadas, apesar de conter 24 componentes diretos.

Achado colateral, mesmo protótipo, não corrigido aqui (ver "Fora de
escopo"): duas databases (`toToggle.db` e `toToggle v2.6.db`) com o mesmo
`html_hash` carregadas ao mesmo tempo — `toToggle.db` veio de uma build
antiga com `--name toToggle` explícito, ficou desatualizada e duplica todas
as telas em `list_screens()` sob dois nomes de documento diferentes.

### P3 — `set_prototype` descrito como "por sessão", mas é por conexão MCP (Achado 5)

`MCPServer._active_doc` vive na instância do processo do servidor, que um
transporte stdio recria a cada nova conexão (ex.: `/mcp` reconectar). A
descrição da tool ("Set the active prototype for **this session**") e as
instruções do agente sugeriam persistência pelo escopo da tarefa; na
prática a seleção se perde silenciosamente em qualquer reconexão, e o
único sintoma é `Multiple prototypes loaded...` reaparecer no meio da
tarefa. Comportamento em si correto para um servidor stdio (não há como
persistir estado de processo através de um restart sem building uma nova
classe de bug — ver "Fora de escopo"); o gap real era só a documentação não
avisar disso.

## Correções

- `mcp/tools.py`: nova tool `get_full_texts(name | screen+section)`,
  espelhando `get_full_styles` exatamente (mesma assinatura, mesmo padrão de
  fallback "não encontrado"). `_truncation_notice` ganha parâmetro `tool`
  (default `"get_full_styles"`) para que o mesmo helper sirva os dois casos.
  Todo call site de truncamento de texto (`get_screen_full` × 2,
  `get_section`, `get_component_spec`, `get_component_full`,
  `validate_component_implementation` × 1) e todo call site de truncamento
  de estilo que ainda não apontava para `get_full_styles`
  (`get_screen_full`, `get_component_spec`, `get_component_full`,
  `validate_component_implementation`) passam a nomear a chamada de volta.
- `extraction/screen_extractor.py`: `ScreenRole.ROOT` — `App` (nome exato,
  não sufixo/prefixo) classifica como tela de nível raiz, ao lado da tabela
  de sufixos existente. `AppCard`/`MiniApp` continuam `COMPONENT`
  (match é por nome exato, não substring).
- `mcp/tools.py` (`set_prototype` description) + `mcp/server.py`
  (`_AGENT_INSTRUCTIONS`): wording corrigido para "esta conexão MCP", com
  nota explícita de que uma reconexão reseta a seleção mesmo no meio da
  tarefa.

## Fora de escopo

- Rótulos de seção estruturalmente detectados para `App`
  (`Section1`..`Section7`, um `Menu`) em vez de nomes como "sidebar"/
  "topbar" — `_detect_by_structure` já nomeia pela primeira string de UI
  encontrada no bloco, caindo em `SectionN` quando não acha uma; `App` não
  carrega comentários `{/* ── Nome ── */}` no prototype real, então a
  estratégia 1 (a mais precisa) nunca dispara para ele. Limitação
  pré-existente do fallback estrutural (mesma classe de problema que C37
  já documentou), não introduzida nem alargada por este change — `App`
  agora É alcançável via `get_screen_full`/`get_full_jsx` (o bloqueio real
  do Achado 3), só não com rótulos de seção "bonitos".
- Deduplicação de documentos com `html_hash` idêntico carregados sob nomes
  diferentes (achado colateral do P2) — é um artefato de build local (dois
  `design-graph <html>` rodados em momentos diferentes, um com `--name`
  explícito), não um bug de extração; a ação certa é o usuário apagar o
  build obsoleto (`toToggle.db`) ou adotar um nome estável deliberadamente.
  Detecção automática de conteúdo duplicado entre documentos carregados
  ficaria como melhoria de produto separada, não pedida por nenhum dos dois
  achados como correção obrigatória.
- Persistir `_active_doc` em disco para sobreviver a uma reconexão —
  cogitado e descartado: este servidor é deliberadamente compartilhado
  entre vários projetos ao mesmo tempo (ver `_AGENT_INSTRUCTIONS`); um
  arquivo de estado global faria uma conexão nova de um projeto B herdar
  silenciosamente o protótipo que a conexão anterior do projeto A deixou
  selecionado — pior que o estado atual (erro explícito, sempre
  corrigível chamando `set_prototype` de novo). Resolvido só na
  documentação (P3 acima).
