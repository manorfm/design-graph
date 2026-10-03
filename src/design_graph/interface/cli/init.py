"""
`design-graph init` — configure the bundled UI-context agent skill for one
or more AI coding tools in a target project.

Each tool has its own convention for "persistent project instructions for
an agent" (skill, rule, steering file, AGENTS.md, ...) — confirmed by
research as of August 2026, not guessed:

  claude       .claude/skills/design-graph-ui-context/SKILL.md  (name+description frontmatter, agent-requested activation)
  cursor       .cursor/rules/design-graph-ui-context.mdc        (description/globs/alwaysApply frontmatter, agent-requested activation)
  codex        AGENTS.md                                        (plain Markdown, no frontmatter, always injected — section
                                                                  appended/updated between markers, never overwrites the whole file)
  antigravity  .agents/rules/design-graph-ui-context.md         (plain Markdown, no frontmatter, always injected, 12,000-char cap)
  kiro         .kiro/steering/design-graph-ui-context.md        (inclusion/name/description frontmatter; inclusion: always)

The canonical content lives once, as the Claude Code SKILL.md itself
(resources/skills/design-graph-ui-context/SKILL.md) — every other target
is derived from its frontmatter (name/description) and body at install
time, instead of shipping four more near-duplicate copies that could drift
out of sync with each other.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Callable

_SKILLS_PACKAGE = "design_graph.resources.skills"
_SKILL_NAME = "design-graph-ui-context"

_AGENTS_MD_START = "<!-- design-graph:ui-context:start -->"
_AGENTS_MD_END = "<!-- design-graph:ui-context:end -->"


@dataclass(frozen=True)
class InitCliArgs:
    target: Path = Path(".")
    tools: tuple[str, ...] | None = None  # None = prompt interactively
    force: bool = False


def parse_init_args(argv: list[str]) -> InitCliArgs:
    parser = argparse.ArgumentParser(
        prog="design-graph init",
        description=(
            "Configure the design-graph UI-context agent skill for one or more "
            "AI coding tools in a project. Prompts interactively when --tool is omitted."
        ),
    )
    parser.add_argument(
        "path", nargs="?", default=".", metavar="PATH",
        help="Target project directory (default: current directory)",
    )
    parser.add_argument(
        "--tool", dest="tools", default=None,
        help=(
            f"Comma-separated tool keys to configure without prompting "
            f"({', '.join(t.key for t in TARGETS)}, or 'all')"
        ),
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite an existing, modified copy",
    )
    parsed = parser.parse_args(argv)
    tools: tuple[str, ...] | None = None
    if parsed.tools:
        tools = _resolve_tool_keys(parsed.tools)
    return InitCliArgs(target=Path(parsed.path), tools=tools, force=parsed.force)


def _resolve_tool_keys(raw: str) -> tuple[str, ...]:
    if raw.strip().lower() in {"all", "a"}:
        return tuple(t.key for t in TARGETS)
    return tuple(key.strip() for key in raw.split(",") if key.strip())


# ── Frontmatter split (name/description only — both always single-line, ──
# ── so a tiny line-based parser is enough; no need for a YAML dependency) ─

def _load_canonical_skill() -> tuple[dict[str, str], str]:
    text = (
        (resources.files(_SKILLS_PACKAGE) / _SKILL_NAME / "SKILL.md")
        .read_text(encoding="utf-8")
    )
    match = re.match(r"^---\n(.*?)\n---\n\n?(.*)$", text, re.DOTALL)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, match.group(2)


# ── Per-tool rendering ───────────────────────────────────────────────────

def _render_claude(meta: dict[str, str], body: str) -> str:
    return f"---\nname: {meta.get('name', _SKILL_NAME)}\ndescription: {meta.get('description', '')}\n---\n\n{body}"


def _render_cursor(meta: dict[str, str], body: str) -> str:
    return (
        f"---\ndescription: {meta.get('description', '')}\nglobs:\nalwaysApply: false\n---\n\n{body}"
    )


def _render_kiro(meta: dict[str, str], body: str) -> str:
    return (
        f"---\ninclusion: always\nname: {meta.get('name', _SKILL_NAME)}\n"
        f"description: {meta.get('description', '')}\n---\n\n{body}"
    )


def _render_antigravity(meta: dict[str, str], body: str) -> str:
    # Plain Markdown, no frontmatter — Antigravity rules are always
    # injected in full, so nothing here is used for conditional activation.
    return body


@dataclass(frozen=True)
class SkillTarget:
    key: str
    label: str
    relative_path: Path
    render: Callable[[dict[str, str], str], str]


TARGETS: tuple[SkillTarget, ...] = (
    SkillTarget("claude", "Claude Code", Path(".claude/skills") / _SKILL_NAME / "SKILL.md", _render_claude),
    SkillTarget("cursor", "Cursor", Path(".cursor/rules") / f"{_SKILL_NAME}.mdc", _render_cursor),
    SkillTarget("codex", "Codex CLI (AGENTS.md)", Path("AGENTS.md"), lambda m, b: b),
    SkillTarget("antigravity", "Google Antigravity", Path(".agents/rules") / f"{_SKILL_NAME}.md", _render_antigravity),
    SkillTarget("kiro", "Kiro", Path(".kiro/steering") / f"{_SKILL_NAME}.md", _render_kiro),
)
_TARGETS_BY_KEY = {t.key: t for t in TARGETS}


def run_init_command(
    args: InitCliArgs,
    prompt: Callable[[str], str] = input,
    checkbox: Callable[[], tuple[str, ...] | None] | None = None,
) -> int:
    if args.tools is not None:
        tools: tuple[str, ...] | None = args.tools
    else:
        picker = checkbox if checkbox is not None else _interactive_checkbox_picker
        tools = picker()
        if tools is None:  # questionary unavailable/not a real TTY — plain-text fallback
            tools = _prompt_for_tools(prompt)
    if tools is None:  # prompt failed (non-interactive stdin) and no --tool given
        print(
            "error: no tools selected and input is not interactive. "
            f"Pass --tool (e.g. --tool claude,cursor or --tool all)."
        )
        return 1

    unknown = [key for key in tools if key not in _TARGETS_BY_KEY]
    if unknown:
        available = ", ".join(_TARGETS_BY_KEY)
        print(f"error: unknown tool(s) {', '.join(unknown)}. Available: {available}")
        return 1
    if not tools:
        print("Nothing selected — nothing to do.")
        return 0

    meta, body = _load_canonical_skill()
    project_root = args.target.expanduser().resolve()
    exit_code = 0
    for key in tools:
        target = _TARGETS_BY_KEY[key]
        ok, message = _install_one(target, project_root, meta, body, args.force)
        print(message)
        if not ok:
            exit_code = 1
    return exit_code


def _interactive_checkbox_picker() -> tuple[str, ...] | None:
    """
    True arrow-key/space-to-toggle multi-select, via the optional
    `questionary` dependency (`pip install design-graph[interactive]`).

    Returns None — not a real answer, a "not available here" signal — so
    the caller falls back to the always-available plain-text numbered
    prompt (_prompt_for_tools). That happens whenever either condition
    isn't met:
      - stdin/stdout aren't a real interactive terminal (a script, CI, or
        any piped input) — a raw-mode checkbox UI has nothing to attach to.
      - `questionary` isn't installed — it's an optional extra, not a hard
        dependency of the base package, so its absence is expected, not an
        error.
    A hint is printed (once) only in the second case, where a human is
    actually at the keyboard and could plausibly want it — never for a
    non-interactive stdin, where it would just be log noise.
    """
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    try:
        import questionary
    except ImportError:
        print("Dica: instale `design-graph[interactive]` para escolher com um menu de setas.\n")
        return None

    choices = [
        questionary.Choice(title=f"{t.label} ({t.relative_path})", value=t.key)
        for t in TARGETS
    ]
    selected = questionary.checkbox(
        "Quais ferramentas você usa neste projeto? (espaço para marcar, enter para confirmar)",
        choices=choices,
    ).ask()
    return () if selected is None else tuple(selected)  # None == Ctrl-C / cancelled


def _prompt_for_tools(prompt: Callable[[str], str]) -> tuple[str, ...] | None:
    print("Quais ferramentas você usa neste projeto?\n")
    for i, target in enumerate(TARGETS, start=1):
        print(f"  {i}) {target.label:<24} ({target.relative_path})")
    print()
    try:
        raw = prompt("Números separados por vírgula, ou 'a' para todas: ").strip()
    except EOFError:
        return None
    if not raw:
        return ()
    if raw.lower() in {"a", "all"}:
        return tuple(t.key for t in TARGETS)
    keys: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if not token.isdigit():
            continue
        index = int(token) - 1
        if 0 <= index < len(TARGETS):
            keys.append(TARGETS[index].key)
    return tuple(keys)


def _install_one(
    target: SkillTarget, project_root: Path, meta: dict[str, str], body: str, force: bool,
) -> tuple[bool, str]:
    dest = project_root / target.relative_path
    if target.key == "codex":
        return _update_agents_md(dest, body, force)

    content = target.render(meta, body)
    if dest.exists():
        if dest.read_text(encoding="utf-8") == content:
            return True, f"[{target.key}] já atualizado — {dest}"
        if not force:
            return False, (
                f"[{target.key}] {dest} já existe e é diferente do conteúdo atual. "
                f"Use --force para sobrescrever."
            )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    return True, f"[{target.key}] instalado → {dest}"


def _update_agents_md(dest: Path, body: str, force: bool) -> tuple[bool, str]:
    """
    AGENTS.md is a shared, project-wide file other tooling may already own
    — install must never overwrite the whole file, only add or refresh a
    clearly marked section of its own, identified by _AGENTS_MD_START/_END.
    """
    section = f"{_AGENTS_MD_START}\n{body}\n{_AGENTS_MD_END}"
    existing = dest.read_text(encoding="utf-8") if dest.exists() else ""

    pattern = re.compile(
        re.escape(_AGENTS_MD_START) + r".*?" + re.escape(_AGENTS_MD_END), re.DOTALL,
    )
    if pattern.search(existing):
        if section in existing:
            return True, f"[codex] já atualizado — {dest}"
        if not force:
            return False, (
                f"[codex] {dest} já tem uma seção design-graph diferente da atual. "
                f"Use --force para atualizar."
            )
        updated = pattern.sub(section, existing)
    else:
        separator = "\n\n" if existing and not existing.endswith("\n\n") else ""
        updated = f"{existing}{separator}{section}\n"

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(updated, encoding="utf-8")
    verb = "atualizado" if existing else "criado"
    return True, f"[codex] {verb} → {dest}"
