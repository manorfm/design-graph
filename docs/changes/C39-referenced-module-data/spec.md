# Spec C39 — Dados de módulo referenciados por nome (ícones, badges) + textos de objeto + skipped_entries visível

## Contexto

Continuação da investigação de C38, disparada por uma pergunta concreta de
outro agente sobre o protótipo `toToggle`: quando um botão usa
`<Icon name="lock" />`, o agente reconstruindo a tela em outro código sabe
*qual* ícone é usado (o call site já é capturado com fidelidade total), mas
não tinha como saber o *desenho* do ícone (o path SVG) — a fonte real
(`const ICONS = { lock: "M21...", ... }`) mora num `const` de módulo, fora
de qualquer função, invisível a toda a extração existente. O pedido
explícito foi: sem heurística de "isso é um ícone" ou "vem de tal
biblioteca" (heurística já tentada e rejeitada em C32) — só um mecanismo
mecânico que anexe o dado exatamente como está no fonte.

Decisão de design tomada em conversa antes da implementação (três pontos,
resolvidos nesta ordem de preferência por "decisão madura"):

1. **Onde o dado mora no grafo**: campo em `Component`, não um node
   dedicado. `IconAsset` (C22) só foi criado depois de evidência real de
   reuso entre vários componentes; aqui só há evidência de referência 1
   para 1 (`Icon`→`ICONS`, `RoleBadge`→`ROLE_META`) — criar um node novo
   agora seria desenhar para um cenário hipotético ainda não observado.
2. **Precisão da detecção**: captura tudo que é referenciado por nome no
   corpo da função, sem tentar filtrar por relevância — qualquer filtro
   seria a heurística que o pedido original queria evitar.
3. **Truncamento**: mesmo padrão já estabelecido em C36/C38 (nunca cortar
   sem apontar como recuperar o resto).

## Problemas resolvidos

### P1 — Dado referenciado por nome fica preso fora de qualquer função

`extraction/module_data_extractor.py` (novo): para cada `const NOME = {...}`/
`[...]` de módulo (mesma varredura de C38's `find_module_level_constants`,
extraída para `parsing/js_parser.py` para ser reutilizável), se o nome
aparece como token no corpo de um componente, o literal inteiro é
convertido para uma estrutura JSON-segura (só valores de string, até 2
níveis de aninhamento — profundidade real confirmada por `ROLE_META`:
`{ root: { label: "Root" } }`) e anexado a esse componente.
`Component.referenced_data_json` (schema v9) persiste isso; `get_component`/
`get_component_spec`/`get_component_full`/`get_screen_full` renderizam numa
seção "Dados referenciados", com o mesmo aviso de corte/escape-hatch que
estilos e textos já têm (nova tool `get_component_data`, espelhando
`get_full_styles`/`get_full_texts`).

Verificado contra o `toToggle v2.6` real: `get_component_spec("Icon")`
agora mostra as 39 entradas de `ICONS` (path SVG completo por nome, ex.
`lock`: `M19 11H5a2 2 0 0 0-2 2v7...`); `get_component_spec("RoleBadge")`
mostra `ROLE_META` aninhado com `bg`/`color`/`label` reais por role.

### P2 — `module_text_extractor.py` só cobria array de objetos, não objeto direto

Achado colateral, mesmo padrão de shared-config: `const ROLE_META = { root:
{ label: 'Root', ... }, ... }` é a mesma convenção de `DETAIL_TABS`-style
arrays, só que indexada por identificador em vez de posição numa lista —
`module_text_extractor.py` só reconhecia `const NOME = [...]`. Estendido
para também reconhecer `const NOME = {...}` (objeto plano ou aninhado um
nível), reaproveitando a mesma varredura de P1 (`find_module_level_constants`).
Verificado: `UITexts` no `toToggle v2.6` real foi de 440 para 492 depois
desta mudança — texto de badge/role antes invisível a `search()`.

### P3 — `skipped_entries` (entrada de bundle que falhou ao decodificar) nunca saía do log

Achado da conversa anterior (C38 não corrigiu, só documentou):
`RawSources.skipped_entries` já existia, mas só virava `logger.warning` em
`source_loader.py` — nunca persistido, nunca queryable por nenhuma tool
MCP. Agora `BuildState.skipped_entries` persiste no `<db>.state.json`
(schema aditivo, default 0 pra estado antigo) e `get_build_diff` inclui um
aviso explícito sempre que > 0 — inclusive nos casos de "primeira build" e
"sem mudança de tela/componente", que antes retornavam cedo sem checar
isso.

## Achado colateral, não corrigido (comentário de linha quebra chave de objeto)

Ao verificar `get_component_data("Icon")` contra o `toToggle v2.6` real, uma
entrada saiu com a chave `"// custom below\n  key"` em vez de `"key"`. Causa
raiz: o fonte real tem

```js
const ICONS = {
  ...
  toggle: null, // custom below
  key: "M21 2l-2 2...",
  ...
};
```

`iter_object_literal_pairs`/`split_top_level` (`parsing/js_parser.py`) não
removem comentários de linha (`//...`) antes de dividir por vírgula — o
comentário gruda no início do próximo par `key: valor`. `toggle: null` já é
descartado corretamente (valor não é string), mas o comentário sobrevive
colado à chave seguinte. Bug pré-existente nessas duas funções
compartilhadas (usadas também por resolução de estilo, props, module
texts) — nunca tinha aparecido porque nenhum consumidor anterior expunha
uma chave bruta de volta para um agente; `get_component_data` é o primeiro
a fazer isso. Fora de escopo aqui: corrigir comentários exigiria uma
varredura de remoção de comentário compartilhada por todo consumidor de
`split_top_level`, superfície bem maior que este change — registrado para
uma investigação própria.

## Fora de escopo

- Detectar *como* um componente indexa o dado referenciado (`ICONS[name]`
  vs `ICONS[props.name]` vs `switch`) — nunca tentado; a regra é puramente
  "o nome do const aparece como token no corpo", sem entender a lógica.
- Recursão além de 2 níveis de objeto/array aninhado — sem evidência real
  de um caso mais profundo que `ROLE_META`.
- Node dedicado para dado compartilhado por múltiplos componentes — ver
  decisão de design acima; promovido para lá só se/quando aparecer
  evidência real de reuso (mesmo critério que já valeu para `IconAsset`/C22).
