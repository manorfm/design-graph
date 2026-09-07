# Roadmap v2.x — motor de extração baseado em AST (tree-sitter)

> **Status: proposta, não iniciada.** Este documento não é um `docs/changes/CXX`
> — não descreve uma mudança feita, testada e verificada, e sim uma direção
> possível pra uma evolução futura, maior que qualquer change individual já
> registrada. Não tem data, não está no backlog ativo, e não deve ser
> interpretado como trabalho planejado — só como registro de uma decisão de
> arquitetura que foi conversada, com o raciocínio completo, pra não precisar
> ser refeita do zero quando (e se) a necessidade aparecer de verdade.

## Contexto: por que isto está sendo escrito agora

O motor de extração (`parsing/js_parser.py`, `extraction/component_extractor.py`,
`extraction/section_extractor.py`, `extraction/module_text_extractor.py`,
`extraction/module_data_extractor.py`) é inteiramente baseado em regex e
varreduras de string balanceadas sobre o texto bruto do bundle — nunca uma
árvore sintática de verdade. Essa escolha foi deliberada (sem depender de
motor JS/Node, rápido, funciona tanto em JSX cru quanto já transpilado) e
funciona bem na prática: o projeto tem 2127+ testes e é usado contra
protótipos reais.

Mas numa única sessão de trabalho (2026-09-06/07, documentada em
`docs/changes/C38` a `C42`), a mesma classe de problema apareceu repetidas
vezes, cada vez num lugar diferente do texto: um comentário de linha grudando
na chave seguinte de um objeto (C40), um `className` escrito como expressão
de template não sendo resolvido (C42), múltiplos `return` na mesma função
perdendo branches inteiros (C36 T80), apóstrofo em prosa JSX desincronizando
o rastreio de aspas pro resto do arquivo (ver `_can_open_quote` em
`js_parser.py`). Nenhum desses foi um bug isolado de descuido — são,
estruturalmente, o mesmo tipo de limitação: regex e varredura de string não
entendem gramática, só padrões locais. Cada um foi corrigido rápido e barato
(menos de uma hora, testado, sem drama) porque são reais mas raros — não é
uma crise, é um padrão que vale documentar antes de esquecer o raciocínio.

## O que um motor baseado em AST resolveria de verdade

Uma árvore sintática real (não um "parser completo" com checagem de tipos —
só uma árvore de sintaxe concreta) elimina essa classe inteira de bug por
construção, porque nunca fica ambíguo o que é comentário, string, JSX ou
código — a gramática já resolve isso, ao contrário de regex que precisa
reimplementar à mão cada caso (`JavaScriptLexicalView`, `_strip_comments`,
`_find_balanced_tag_end`, `_can_open_quote` — tudo isso é gramática
reimplementada em Python).

Além de eliminar bugs já conhecidos, abriria capacidade que hoje é
genuinamente impossível com regex:

- **Resolver `className={"sidebar" + (open ? " open" : "")}` por completo**
  — hoje (C42) só o literal do início é capturado; com uma árvore + avaliação
  de expressão simples, os dois valores possíveis (`"sidebar"` e
  `"sidebar open"`) seriam resolvidos.
- **Resolução de escopo real** — hoje "o componente referencia `ICONS`" (C39)
  é feito procurando o texto "ICONS" em qualquer lugar do corpo da função;
  uma AST permite saber se aquele identificador realmente resolve pro
  `const` de módulo, ou pra uma variável local sombreando ele. (Importante:
  a árvore por si só não faz isso de graça — dá a estrutura certa pra
  escrever essa lógica em cima, em vez de escrever em cima de texto casado
  por regex.)
- **Grafo de controle real** pros múltiplos `return`/guard clauses (hoje
  `{[return_branch:N]}` é rotulagem linear, não uma análise de alcançabilidade
  de verdade).
- **Suporte a `import`/`export` ES real**, se algum dia aparecer um protótipo
  montado por bundler de verdade (webpack/esbuild) em vez do padrão "tudo
  global" que os dois protótipos de referência (`toToggle`, `iPede Manager`)
  usam hoje. Isso é literalmente impossível de fazer direito com regex.
- **TypeScript/TSX**, se algum dia precisar — hoje não há nenhuma evidência
  de necessidade (os dois protótipos de referência são `.jsx`/`.js` puro).

## O que NÃO seria resolvido — a árvore não substitui a heurística de domínio

Uma AST de sintaxe não elimina a lógica de negócio que já existe em cima do
texto — só troca o alicerce por um confiável:

- "Esta função realmente renderiza algo visual" (`VisualFunctionCandidate`)
  continua sendo heurística de domínio, agora escrita em cima da árvore.
- Resolução de cascata CSS (`css_class_resolver.py`) é um problema
  separado — se algum dia justificar, teria sua própria decisão (ex.:
  `tinycss2`, um parser de CSS real em Python), independente desta proposta.
- Nenhuma "eficiência" automática: montar uma árvore inteira faz mais
  trabalho por byte lido do que uma passada de regex em C — o ganho real é
  eliminar passadas redundantes sobre o mesmo texto (hoje `find_all_boundaries`,
  `find_module_level_constants` e a janela de cada `extract_component`
  escaneiam o mesmo trecho mais de uma vez, cada um com um propósito), não
  "regex é lento".

## Dependência recomendada — e por que não outras

**`tree-sitter` + `tree-sitter-javascript`** (Python, via `pip`), verificado
em 2026-09-07 direto nas fontes:

- `tree-sitter-javascript` já inclui gramática de JSX no mesmo pacote —
  README oficial: *"JavaScript and JSX grammar for tree-sitter... with
  extensions to support JSX syntax"* — cobre `.js`/`.jsx` num pacote só.
- Se algum dia precisar de TypeScript: `tree-sitter-typescript` é um pacote
  separado que expõe **duas** gramáticas (`typescript` pra `.ts` sem JSX,
  `tsx` pra TypeScript+JSX combinados) — não precisaria disso agora, dado
  que nenhum protótipo de referência usa TS.
- Bindings oficiais em Python (`py-tree-sitter`, mantido pelo próprio grupo
  tree-sitter) — instalação 100% via `pip`, sem exigir Node/runtime JS na
  máquina de quem usa o `design-graph`. Preserva a promessa central do
  projeto (`pip install`/`pipx install`, nada mais).
- Confirmado por busca: tree-sitter é a solução dominante do ecossistema em
  2026, ativamente mantido, usado em produção por GitHub (navegação de
  código), Neovim, Helix, entre outros — não é uma aposta em ferramenta de
  nicho.
- É um parser **tolerante a erro**: constrói árvore parcial mesmo diante de
  JS malformado/gerado — importante porque bundle de vendor minificado nem
  sempre é "limpo o suficiente" pra um parser estrito.

**Alternativas descartadas, com o motivo**:

| Opção | Por que não |
|---|---|
| Rodar Babel/TypeScript compiler via subprocess Node | Quebra a promessa de instalação só-Python; exige Node na máquina de quem usa |
| Embutir um motor V8 (`STPyV8` e similares) | Dependência pesada, binário grande, resolve o mesmo problema que tree-sitter resolve mais leve |
| Parser baseado em ANTLR4 pra Python (`lexanth/python-ast`) | Nicho, muito menos maduro/testado que tree-sitter |
| Reescrever o projeto inteiro em Node/TypeScript | Ver seção seguinte |

### Por que não reescrever o projeto em Node (ou outra linguagem)

O ganho de trocar de linguagem sobre "usar tree-sitter a partir do Python" é
marginal — acesso a essencialmente o mesmo parser — mas o custo é
desproporcional: portar (ou re-verificar do zero) ~5.900 linhas de
extração/grafo/MCP hoje cobertas por 2127+ testes, e as mais de 40 correções
documentadas em `docs/changes/` (cada uma achada testando contra protótipo
real, não por especulação). Reescrever arrisca reintroduzir silenciosamente
bugs já resolvidos, sem garantia de equivalência comportamental a menos que
o histórico de testes inteiro seja portado junto. É resolver um problema
estreito (precisão de parsing) com substituição total do sistema.

## Escopo do que mudaria (se/quando executado)

Camada de extração inteira, módulo a módulo:

- `parsing/js_parser.py` — `find_all_boundaries`, `find_matching_delimiter`,
  `JavaScriptLexicalView`, `_strip_comments`, `find_module_level_constants`
  etc. viram, em grande parte, consultas sobre a árvore em vez de regex
  reimplementando gramática.
- `extraction/component_extractor.py`, `extraction/section_extractor.py`,
  `extraction/module_text_extractor.py`, `extraction/module_data_extractor.py`
  — cada extrator passa a percorrer nós da árvore (`jsx_element`,
  `call_expression`, `variable_declarator`, etc.) em vez de casar regex
  contra uma janela de texto.
- `parsing/css_class_resolver.py` — decisão separada, fora do escopo desta
  proposta (CSS não é JS; um parser de CSS real seria uma escolha
  independente, se algum dia justificar).

Estimativa honesta: não é um refactor de fim de semana — é trabalho de
meses, no mesmo estilo disciplinado que este projeto já demonstra (TDD, um
extractor por vez, verificado contra os dois protótipos de referência antes
de seguir pro próximo).

## Estratégia de migração, se executado

1. **Modo sombra antes de qualquer corte**: rodar as duas pipelines
   (regex atual + AST nova) em paralelo sobre os mesmos protótipos de
   referência (`toToggle v2.6.html`, `iPede Manager v21.2.html`),
   comparando saída campo a campo, antes de trocar qual delas é a fonte de
   verdade em produção.
2. **Um extractor por vez**, começando pelo de menor superfície
   (`module_data_extractor.py`, o mais novo e mais simples) até o de maior
   (`component_extractor.py`, 639 linhas, o coração do pipeline).
3. **Re-verificar as 40+ correções já documentadas** (`docs/changes/C01` a
   `C42`) uma a uma contra a nova pipeline — cada uma tem seu próprio "como
   reproduzir" já escrito, então isso é checagem, não re-investigação.
4. Suíte de testes existente (2127+) como rede de segurança contínua durante
   a migração — nenhum módulo é considerado migrado até a suíte inteira
   (unit + integration + guardrails) passar de novo sobre ele.

## Gatilho — quando isto deveria sair do papel

Não é uma data, é uma condição: quando o ritmo de bugs de edge-case da
classe descrita acima (algo que só uma gramática real resolveria, não mais
um regex/heurística pontual) começar a custar tempo real de forma repetida
— não porque "AST é melhor" em abstrato. Enquanto cada bug dessa classe
continuar custando menos de uma hora pra achar, corrigir e testar (como
todos os de C38–C42 custaram), a resposta certa continua sendo o ciclo
incremental atual, não esta migração.
