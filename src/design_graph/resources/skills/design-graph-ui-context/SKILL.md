---
name: design-graph-ui-context
description: Antes de criar, alterar, atualizar, corrigir ou revisar uma tela, componente ou detalhe visual — inclusive quando o pedido for só "atualizar a tela/o frontend a partir do protótipo" — consulte o servidor MCP design-graph para buscar o contexto exato (fonte, estilos por estado, tokens, props, hierarquia) em vez de reler o protótipo HTML inteiro ou adivinhar. Qualquer menção a "protótipo" junto de UI já é sinal de usar este skill. Use sempre que a tarefa envolver UI e houver um protótipo rastreado pelo design-graph disponível — pular esta checagem quando a tarefa não tiver nenhuma relação com tela/componente/estilo/protótipo.
---

# Contexto de UI via design-graph

Este projeto pode ter um protótipo HTML (React bundlado via Claude Artifacts,
Cursor Composer, v0, etc.) já convertido em grafo pelo `design-graph` e
exposto via MCP. Esse grafo existe para uma coisa: você não precisar carregar
o HTML inteiro do protótipo (50–200k tokens) no contexto só para saber como
um botão, uma seção ou uma tela inteira deveriam ficar. Use-o.

## Quando usar

Qualquer tarefa que envolva construir, replicar, corrigir, **atualizar** ou
evoluir uma tela, um componente ou um detalhe visual que tenha
correspondência num protótipo já processado — incluindo pedidos formulados
como "atualizar a tela X a partir do protótipo", "atualizar o frontend com
base no protótipo" ou "sincronizar com o protótipo", mesmo sem a palavra
"implementar"/"construir" aparecer. Se a tarefa não tem nada a ver com UI ou
protótipo, ignore este skill e siga normalmente.

## Passo 0 — o servidor está disponível?

Procure por ferramentas `mcp__design-graph__*` (ou `design-graph`/
`design-mcp` no nome do servidor MCP conectado). Se não encontrar nenhuma:

- Pergunte se existe um protótipo HTML de referência para esta tela antes de
  implementar de memória/adivinhação.
- Se existir mas o grafo nunca foi construído, sugira rodar
  `design-graph <prototipo.html>` uma vez (fora desta sessão, o usuário
  decide se quer instalar/rodar).
- Se não existir protótipo nenhum, siga sem este skill.

Se as ferramentas existirem, sempre prefira consultá-las a reler o HTML bruto
do protótipo diretamente — reler o arquivo inteiro contradiz o propósito do
grafo.

## Passo 1 — selecionar o protótipo certo

O mesmo servidor MCP costuma ficar conectado em vários projetos ao mesmo
tempo, então mais de um protótipo pode estar carregado.

```
list_screens()                        # veja o que está disponível
set_prototype(name="nome-do-proto")   # fixa o protótipo pro resto da tarefa
```

Chame `set_prototype` uma vez no início da tarefa em vez de passar `doc=` em
toda chamada subsequente.

## Passo 2 — encontrar a tela/componente certo

```
search(query="texto ou nome aproximado")   # aceita nome parcial, PT/EN
list_screens()                             # lista telas de todos os protótipos
list_components(comp_type="modal")         # filtra por tipo semântico
```

`search`/as demais tools fazem fuzzy match — não precisa do nome exato.

## Passo 3 — buscar o contexto certo pro tamanho da tarefa

| Situação | Tool | Por quê |
|---|---|---|
| Construir/replicar uma tela inteira | `assemble_page(name, known=[…])` | Esqueleto da tela, cada componente uma vez, dados que eles repetem, tokens por modo e dependências — numa chamada; `known` deixa de fora os componentes que você já recebeu |
| Inspecionar uma tela sem montá-la | `get_screen(name)` · `get_screen(name, detail="full")` | Seções e componentes pelo nome; com `full`, cada seção e componente inteiros |
| Só a estrutura/layout de uma tela, sem detalhe visual completo | `get_screen(name, detail="layout")` | Mais leve, só profile de layout por componente |
| Um componente isolado (botão, card, input) | `get_component(name)` | Spec única focada em reconstrução: estilos por estado, tokens, interações, props, hierarquia, telas que usam |
| Um componente complexo com filhos aninhados (modal, form, card com sub-widgets) | `get_component(name, depth=3)` | Componente + os aninhados (até 3 níveis) numa chamada só |
| Uma seção específica de uma tela | `get_screen(name, section=…)` | Estilos, textos, componentes e fonte só daquela seção |
| Fontes, imagens e bibliotecas que a tela usa | `get_resources(screen=…)` · `get_asset(name)` | O que declarar no projeto (bibliotecas, `@import` de fontes) e os arquivos de fontes/imagens gravados no workspace — nunca recriar um ícone ou adivinhar uma fonte |
| Quem usa X / o que muda se X mudar | `impact(name)` | Componente, tela, token pelo nome ou um valor literal (`#FFB81C`) |

**Sempre chame `get_tokens(category?, screen?)` antes de escrever um valor
literal de cor/espaçamento/tipografia/sombra/raio.** Reaproveite o token
existente em vez de inventar um valor novo — é assim que a implementação
fica consistente com o resto do design system do protótipo.

## Passo 4 — quando uma resposta encurta algo

A captura não descarta nada. Quando uma resposta encurta uma lista ou um
fonte para caber, ela termina com um aviso que traz a chamada exata que
devolve o resto:

```
get_full(name, aspect="source")   # fonte como escrito, em partes (part=N) se for longo
get_full(name, aspect="styles")   # todos os estilos (ou screen= + section= de uma seção)
get_full(name, aspect="texts")    # todos os textos
get_full(name, aspect="data")     # dados que o componente referencia (ex.: tabela de ícones)
```

## Passo 5 — depois de implementar, valide (opcional, mas recomendado)

```
validate_component_implementation(name, source)
```

Compara o fonte que você escreveu contra a spec já no grafo (filhos, estilos
default, textos) e aponta divergências. É *best-effort*: pega com confiança
filhos/estilos inline/textos ausentes, mas **não** verifica estilos vindos de
classes CSS customizadas do protótipo nem cores utilitárias do Tailwind (ex.
`bg-blue-500`) — essas exigem a folha de estilo original, que não existe
isolada. Um relatório limpo significa "nenhum sinal de alerta encontrado",
não "correspondência pixel-perfeita garantida".

## Passo 6 — protótipo mudou desde a última consulta?

```
get_build_diff(doc?)   # telas/componentes adicionados/removidos desde a última build
```

Se parecer desatualizado (o protótipo real mudou mas o grafo não reflete),
peça para reconstruir: `design-graph <prototipo.html> --force`.

## Regra geral

Nunca leia o arquivo HTML bruto do protótipo diretamente enquanto o
design-graph tiver esse protótipo carregado — isso anula o motivo de ele
existir (reduzir tokens de contexto e aumentar precisão). Use as tools acima
para obter exatamente o que a tarefa precisa, nada mais.

---

*Este conteúdo é genérico e não referencia nenhum protótipo ou projeto
específico. Configure-o em qualquer projeto frontend com
`design-graph init [PATH]` (Claude Code, Cursor, Codex CLI, Antigravity ou
Kiro) — ver `design-graph init --help`.*
