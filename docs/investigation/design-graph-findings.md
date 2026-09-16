# design-graph findings

Achados de investigações pontuais sobre divergências reportadas entre uma tela
implementada em `server/web` e o protótipo de origem indexado pelo
design-graph — registrados aqui quando a investigação conclui que a causa
**não** é uma lacuna de extração/indexação da ferramenta.

## Achado 1 — TeamsView sem estado de loading não é lacuna do design-graph

**Sintoma:** `server/web/src/components/TeamMembersSection.tsx` faz
`GET /teams/:id/approvers` (chamada de rede assíncrona real) e mostra um
placeholder "Carregando…" (`.empty-ph`) até a resposta chegar. O usuário
reportou que a tela ainda parece "diferente do protótipo", especialmente logo
após criar um time (0 membros), quando esse "Carregando…" aparece
brevemente sem equivalente aparente no protótipo `toToggle`.

**Comando de reprodução:**

```
set_prototype(name="toToggle")
get_full_jsx(name="TeamsView")
get_full_texts(name="TeamsView")
search("loading")
search("carregando")
search("skeleton")
search("spinner")
list_screens()
list_components()
```

**Resultado:**

- `get_full_jsx("TeamsView")` — corpo inteiro é síncrono: `teams.map(t => ...)`
  direto, sem nenhum branch condicional de loading/erro. O único ramo
  condicional é `rows.length === 0` (empty state "No members yet"), que é
  puramente derivado de `t.members` já presente em memória — não de uma
  requisição em andamento.
- `get_full_texts("TeamsView")` — 9 textos completos, nenhum menciona
  loading/carregando/aguarde.
- `search("loading")` e `search("carregando")` — nenhum resultado em nenhum
  documento carregado (incluindo `toToggle` e `ipede_manager_v21.2`).
- `search("skeleton")` e `search("spinner")` — resultados existem, mas
  **só** no documento `ipede_manager_v21.2` (`Skeleton`, `SkeletonText`,
  `SkeletonCard`, `SkeletonList`, classe CSS `.skeleton`, `Spinner`). Esse é
  um protótipo diferente, sem relação com `toToggle`.
- `list_screens()` — as 10 telas de `toToggle` (`App`, `HistoryView`,
  `LoginScreen`, `ActivityView`, `UsersView`, `TeamsView`, `ApprovalsView`,
  `FirstLoginScreen`, `KeysView`, `ApprovalSettingsView`) não incluem nenhuma
  tela de loading/estado assíncrono.
- `list_components()` (59 componentes de `toToggle`) — nenhum componente
  genérico de loading/skeleton/spinner/estado assíncrono em nenhuma tela do
  protótipo.

**Conclusão:** o protótipo `toToggle` nunca foi desenhado com um estado de
loading em lugar nenhum (não é específico de `TeamsView`) porque ele nunca
simula uma chamada de rede assíncrona — todos os dados (`teams`, `users`,
`members`) chegam como props já resolvidas, em memória. O design-graph está
extraindo e reportando corretamente o que existe no protótipo: a ausência de
loading é uma característica genuína da fonte, não um corte/lacuna da
extração. Não há bug a corrigir no design-graph.

A divergência percebida pelo usuário é esperada e worth mantendo: a
implementação real (`TeamMembersSection.tsx`) precisa fazer fetch de verdade
e portanto tem um estado que o protótipo — síncrono por construção — nunca
precisou desenhar. Se esse estado de loading deve ter uma aparência
específica (skeleton, spinner, etc.), isso é uma decisão de design nova a ser
tomada e adicionada ao protótipo de origem (Figma ou equivalente), não algo
para "recuperar" via indexação — não existe no protótipo para ser recuperado.
