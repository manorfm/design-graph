# Plan C38

## Critério de aceite

```bash
pytest tests/unit -q
pytest tests/integration -q
pytest tests/test_architecture_guardrails.py -q
design-graph "toToggle v2.6.html" --force
design-graph validate --db "$(design-graph db 2>/dev/null | true; echo ~/.local/share/design-graph/'toToggle v2.6.db')"
```

## Ordem de implementação

```
T85  mcp/tools.py                                    — P1 (get_full_texts + recoverable_via)
T86  extraction/screen_extractor.py                  — P2 (ScreenRole.ROOT)
T87  mcp/tools.py + mcp/server.py                    — P3 (wording)
```

## T85 — P1: `get_full_texts` + `recoverable_via` consistente

- `_truncation_notice(total, shown, recoverable_via=None, tool="get_full_styles")`
  — mesma assinatura, novo parâmetro `tool` só para trocar qual chamada a
  notícia nomeia. Sem quebra: todo call site existente que já passava
  `recoverable_via` sem `tool` continua apontando para `get_full_styles`.
- `get_full_texts(reader, name, screen, section)` — mesma estrutura de
  `get_full_styles`: `screen+section` via `reader.get_section`, `name` via
  `reader.get_component_spec`; sem fallback de classe CSS (texto não tem
  equivalente ao `find_styles_by_class` de C36 P3 — uma classe CSS não
  carrega texto próprio). Registrada em `TOOL_DEFINITIONS` e no
  `dispatch_map` do `ToolDispatcher`.
- Todo call site de texto truncado (`get_screen_full` seções e componentes,
  `get_section`, `get_component_spec`, `get_component_full`,
  `validate_component_implementation`) passa `recoverable_via` +
  `tool="get_full_texts"`. Todo call site de ESTILO truncado que ainda não
  tinha `recoverable_via` (`get_screen_full` componentes,
  `get_component_spec` — só o bloco default, não o responsivo/`@media`
  porque `get_full_styles` não cobre média queries —,
  `get_component_full`, `validate_component_implementation`) ganha
  `recoverable_via=cname`.

## T86 — P2: `ScreenRole.ROOT`

- Novo membro `ScreenRole.ROOT = "root"`.
- `ScreenIdentity.classify`: primeiro teste da função,
  `if name == _ROOT_COMPONENT_NAME: return cls(name=name, role=ScreenRole.ROOT)`
  — `_ROOT_COMPONENT_NAME = "App"`, match exato (não sufixo/prefixo,
  não reabre a exclusão deliberada de C17 para Panel/Tab/List/Section/Modal).
  `is_top_level` já retorna `True` para qualquer role que não seja
  `COMPONENT`, então nenhuma outra mudança é necessária para `App` entrar em
  `list_screens()`/`is_screen()`.

## T87 — P3: wording de `set_prototype`

- `mcp/tools.py`: descrição de `set_prototype` em `TOOL_DEFINITIONS` —
  "this session" → "this MCP connection", com a frase explícita sobre
  reconexão resetar a seleção mesmo no meio da tarefa.
- `mcp/server.py`: `_AGENT_INSTRUCTIONS` ganha a mesma nota, junto da
  instrução existente de chamar `set_prototype` uma vez no início da
  tarefa.
- Sem mudança de comportamento — só texto lido por quem configura/usa a
  tool. Testes existentes (`test_server_sdk_wiring.py`) checam substrings,
  não o texto exato; nenhum ajuste de teste necessário além de confirmar que
  continuam passando.

## Validação end-to-end — executada em 2026-09-06

```
pytest tests/unit -q                              → 1887 passed
pytest tests/integration -q                        → 155 passed
pytest tests/test_architecture_guardrails.py -q    → 22 passed
design-graph "toToggle v2.6.html" --force          → screens=10 comps=59 sections=22
design-graph validate --db ".../toToggle v2.6.db"  → status=ok errors=0 warnings=0
```

Verificado manualmente via MCP, contra o `toToggle v2.6` real (mesmo caso
mínimo dos dois relatos originais):

- `list_screens()` — `App` (24 componentes) agora aparece entre as telas de
  `toToggle v2.6`, ao lado de `LoginScreen`/`HistoryView`/etc. (antes,
  ausente).
- `get_screen_full(name="App")` — devolve a shell inteira (sidebar/topbar/
  roteamento de view + os 24 componentes diretos), 7 seções detectadas
  estruturalmente (`Section1`/`Section2`/`Menu`/`Section4`-`7` — ver spec.md
  "Fora de escopo" sobre os rótulos genéricos).
- `get_section(screen="App", section="Menu")` — funciona (antes, "seção não
  encontrada em 'App'" para QUALQUER nome de seção, porque `App` não existia
  como tela).
- `get_full_texts(name="App")` / `get_full_texts(screen="App",
  section="Menu")` — lista completa sem "+N mais".
- `get_component_spec("App")` / `validate_component_implementation("App",
  ...)` — toda notícia de truncamento de texto e de estilo agora nomeia a
  chamada de volta (`get_full_texts(App)` / `get_full_styles(App)`).

Achado colateral não corrigido nesta mudança (ver spec.md "Fora de
escopo"): `toToggle.db` (build antiga, `--name toToggle` explícito,
`html_hash` idêntico a `toToggle v2.6.db`) continua carregada e duplicando
as 9 telas menores em `list_screens()` sob o nome de documento `toToggle`.
Remoção manual recomendada ao usuário:
`rm ~/.local/share/design-graph/toToggle.db*`.
