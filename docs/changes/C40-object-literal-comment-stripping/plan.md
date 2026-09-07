# Plan C40

## T95 — `_strip_comments` em `parsing/js_parser.py`

Chamada no início de `split_top_level`, antes do split por vírgula.
Reaproveita `JavaScriptLexicalView.analyze(text).ignored_ranges`
(já existente): um range que abre com `/` é comentário e vira espaços; um
range que abre com aspas é string real, intocado. Sem parâmetro novo, sem
mudança de assinatura — `split_top_level`/`iter_object_literal_pairs`
continuam com a mesma interface pública para os três consumidores
(`parse_object_literal_props`, `module_text_extractor.py`,
`module_data_extractor.py`).

Testes novos em `tests/unit/parsing/test_js_parser.py`
(`TestSplitTopLevelStripsComments`, mais um caso em
`TestIterObjectLiteralPairs` reproduzindo a forma exata do `ICONS` real).
Suíte completa e rebuild real cobertos em spec.md.
