# T37 — Tokenização de busca por termos

**Arquivos:** `src/design_graph/mcp/search.py`
**Depende de:** —
**Status:** `[x] done`

## Responsabilidade

Fazer `search()` encontrar componentes/telas/tokens/textos quando a query
tem mais de uma palavra, ranqueando por quantos termos da query cada
resultado cobre — sem introduzir regex compilada a partir de entrada
externa.

## Critério de aceite

- `expand_query` tokeniza a query por espaço em branco antes de expandir
  aliases; cada termo é expandido individualmente (comportamento de alias
  por termo isolado preservado, não mais aplicado à frase inteira).
- Query de dois ou mais termos que não existem juntos em nenhum nome, mas
  existem cada um isoladamente em nomes diferentes, retorna ambos os
  nomes — comportamento hoje ausente (query inteira == zero resultados).
- Resultado ordenado primeiro por cobertura de termos (fração da query
  encontrada no nome), depois pelo score de match já existente
  (exato/prefixo/sufixo/substring) como desempate.
- Nenhuma comparação usa `re.compile`/`re.search` sobre a query recebida —
  só operações de string (`split`, `in`, `startswith`, `endswith`,
  igualdade) — ver Segurança em `spec.md`.
- `MAX_TOKENS_IN_SEARCH_QUERY_EXPANSION` continua sendo o teto de termos
  processados por chamada (já existente, reusado sem mudança de valor).
- Regressão: toda query de uma palavra usada pelos testes atuais de
  `search.py` mantém o mesmo score e ranking relativo.
- Suíte completa (`pytest tests/unit/ -q`) sem regressão.

## Fora de escopo

- Distinguir "termo não indexado" de "termo que não existe" — ver
  `spec.md` → Fora de escopo. Este task só corrige a tokenização; a
  ambiguidade residual de zero-resultados continua.
- Busca fuzzy/tolerante a erro de digitação — não pedido, não relatado
  como gap.
