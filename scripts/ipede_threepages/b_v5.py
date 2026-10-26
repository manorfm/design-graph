"""Generation-only B repetition; frozen A/v3 and all historical runs stay read-only."""
from .b_v4 import run_b_v4

# Canonical generation task, not a precedence override appended to an inherited
# browser/server task. The complete private diff is recorded before any setup.
GENERATION_BASE = '''Build THREE DIFFERENT executable HTML pages from input/, reproducing each selected route in selection.json at its frozen default state. Write page-1.html, page-2.html, page-3.html in output/ in selection order, and any required local assets. Reconstruct each page and its relevant interactions; do not copy, embed, iframe, or bootstrap the whole application. Retain the relevant shared shell. Use the supplied source and resources only; no network, web, apps, other agents, earlier runs, evaluator files, original rendered DOM or screenshots. Work only in this work directory. Do not inspect parent directories, auth/config files, or other work directories. Do not install dependencies. Output must work offline with local assets, data or blob URLs. Match both 1280x900 and 390x844 with fresh empty storage, pt-BR locale and America/Fortaleza timezone; fixed date 2026-10-26T12:00:00Z. Implement functional controls relevant to each page. You have 900 seconds and 90 tool calls total for all three pages. Do not self-report artifact timestamps or token splits.
GENERATION ONLY: Generate output/page-1.html, output/page-2.html, output/page-3.html and required assets, then finish. Do not start or open any server or listener, including loopback. Do not launch or use a browser, browser automation, screenshots or browser self-evaluation. Evaluation is a separate evaluator-only phase after this session. Do not use a proxy, alternate listener, or alternative API to bypass these restrictions or any refusal. Any guard or policy refusal stops the action immediately; do not retry or seek a workaround. The required native design-graph MCP stdio connection is the only MCP transport; do not replace it or use another server. Common source files are supplied inputs, not a fallback for missing MCP evidence.
'''


def run_b_v5(root, baseline, python, worktree):
    return run_b_v4(root, baseline, python, worktree, version='v5', base_prompt=GENERATION_BASE)
