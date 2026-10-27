"""Frozen symmetric experiment declarations, with no source locations or answers."""
MODEL = 'gpt-6.1-sol'
EFFORT = 'medium'
ORDER = [(1, 'A'), (1, 'B'), (2, 'B'), (2, 'A'), (3, 'A'), (3, 'B')]
COMMON = '''Reconstruct the single target described in target.json using the supplied source and assets in input/ to understand it. Write exactly output/page.html, with NEW CSS and new vanilla JavaScript where needed. Reproduce its shared shell, initial state and observable local interactions. Do not invent a backend, downloads or behavior of inert controls. Match 1280x900 and 390x844, pt-BR, America/Fortaleza, empty storage, fixed date 2026-10-26T12:00:00Z.
You may inspect source and mechanically decode the complete bundle. Do not extract, transpile, copy or transplant original CSS, components, application scripts or frameworks into your output. No iframe, whole-app bootstrap, screenshot/image as page, framework, browser, browser automation, listener, server, network, web, apps, agents, dependency installation or self-evaluation. Produce an independent implementation. Original static images may be used as assets only.
Work only here. Keep decoded source, all intermediates, caches and temporary files inside this workspace or its exclusive TMPDIR. The authorized physical workspace may be under /tmp. Use /tmp only inside this workspace or its exclusive TMPDIR; never use global /tmp, parents, siblings or other global paths. Do not perform destructive cleanup during collection; do not use rm -rf or variants. Do not inspect parent directories, credentials, configuration, oracle, historical runs or evaluator material. Do not dump the entire source by default. Source understanding is allowed. Stop immediately on any guard or policy refusal; never retry via an alternative executor, API, tunnel or transport. If required capabilities are unavailable, stop and report the failure.
Budget: 900 seconds and 120 operations, one fresh session for this target. Finish after writing the single HTML. Evaluation is separate. Do not report invented usage, timing or money.
'''
CONDITIONS = {
 'A': 'CONDITION A: Use files and search only. MCP is unavailable and prohibited.\n',
 'B': 'CONDITION B: Use the same files and search plus native design-graph MCP. Before ANY implementation write, complete a useful native query relevant to the target by its semantic name, returning substantive source or design information. Discovery/listing alone, irrelevant calls and source fallback for missing MCP evidence do not qualify. Stop if MCP is unavailable.\n',
}


def prompt(lane):
    return COMMON + CONDITIONS[lane]
