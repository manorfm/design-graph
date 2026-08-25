from pathlib import Path

import pytest

from design_graph.cli.init import (
    InitCliArgs,
    TARGETS,
    parse_init_args,
    run_init_command,
)


class TestParseInitArgs:
    def test_defaults_to_current_directory_and_no_tools(self):
        args = parse_init_args([])
        assert args.target == Path(".")
        assert args.tools is None
        assert args.force is False

    def test_accepts_explicit_path(self):
        args = parse_init_args(["/some/project"])
        assert args.target == Path("/some/project")

    def test_tool_flag_splits_on_comma(self):
        args = parse_init_args(["--tool", "claude,cursor"])
        assert args.tools == ("claude", "cursor")

    def test_tool_flag_all_expands_to_every_target(self):
        args = parse_init_args(["--tool", "all"])
        assert set(args.tools) == {t.key for t in TARGETS}

    def test_force_flag(self):
        args = parse_init_args(["--tool", "claude", "--force"])
        assert args.force is True


class TestRunInitCommandNonInteractive:
    def test_installs_claude_skill(self, tmp_path, capsys):
        code = run_init_command(InitCliArgs(target=tmp_path, tools=("claude",)))
        assert code == 0
        dest = tmp_path / ".claude" / "skills" / "design-graph-ui-context" / "SKILL.md"
        assert dest.exists()
        text = dest.read_text(encoding="utf-8")
        assert text.startswith("---\nname: design-graph-ui-context")
        assert "instalado" in capsys.readouterr().out

    def test_installs_cursor_rule_with_mdc_frontmatter(self, tmp_path):
        run_init_command(InitCliArgs(target=tmp_path, tools=("cursor",)))
        dest = tmp_path / ".cursor" / "rules" / "design-graph-ui-context.mdc"
        text = dest.read_text(encoding="utf-8")
        assert text.startswith("---\ndescription:")
        assert "alwaysApply: false" in text
        assert "name:" not in text.split("---")[1]  # cursor frontmatter has no `name` field

    def test_installs_kiro_steering_with_inclusion_always(self, tmp_path):
        run_init_command(InitCliArgs(target=tmp_path, tools=("kiro",)))
        dest = tmp_path / ".kiro" / "steering" / "design-graph-ui-context.md"
        text = dest.read_text(encoding="utf-8")
        assert "inclusion: always" in text

    def test_installs_antigravity_rule_without_frontmatter(self, tmp_path):
        run_init_command(InitCliArgs(target=tmp_path, tools=("antigravity",)))
        dest = tmp_path / ".agents" / "rules" / "design-graph-ui-context.md"
        text = dest.read_text(encoding="utf-8")
        assert not text.startswith("---")
        assert text.startswith("#")

    def test_creates_agents_md_for_codex_when_absent(self, tmp_path):
        run_init_command(InitCliArgs(target=tmp_path, tools=("codex",)))
        dest = tmp_path / "AGENTS.md"
        text = dest.read_text(encoding="utf-8")
        assert "<!-- design-graph:ui-context:start -->" in text
        assert "<!-- design-graph:ui-context:end -->" in text
        assert not text.startswith("---")  # AGENTS.md has no frontmatter at all

    def test_agents_md_appends_without_touching_existing_content(self, tmp_path):
        dest = tmp_path / "AGENTS.md"
        dest.write_text("# My project\n\nRun `pytest` to test.\n", encoding="utf-8")
        run_init_command(InitCliArgs(target=tmp_path, tools=("codex",)))
        text = dest.read_text(encoding="utf-8")
        assert "# My project" in text
        assert "Run `pytest` to test." in text
        assert "<!-- design-graph:ui-context:start -->" in text

    def test_agents_md_rerun_is_idempotent(self, tmp_path):
        run_init_command(InitCliArgs(target=tmp_path, tools=("codex",)))
        dest = tmp_path / "AGENTS.md"
        first = dest.read_text(encoding="utf-8")
        code = run_init_command(InitCliArgs(target=tmp_path, tools=("codex",)))
        assert code == 0
        assert dest.read_text(encoding="utf-8") == first

    def test_agents_md_update_replaces_only_the_marked_section(self, tmp_path):
        dest = tmp_path / "AGENTS.md"
        dest.write_text(
            "# Notes\n\n"
            "<!-- design-graph:ui-context:start -->\nSTALE CONTENT\n<!-- design-graph:ui-context:end -->\n\n"
            "## Deploy\nsee deploy.md\n",
            encoding="utf-8",
        )
        run_init_command(InitCliArgs(target=tmp_path, tools=("codex",), force=True))
        text = dest.read_text(encoding="utf-8")
        assert "STALE CONTENT" not in text
        assert "## Deploy" in text
        assert "see deploy.md" in text

    def test_installs_all_five_targets(self, tmp_path):
        code = run_init_command(InitCliArgs(target=tmp_path, tools=tuple(t.key for t in TARGETS)))
        assert code == 0
        assert (tmp_path / ".claude" / "skills" / "design-graph-ui-context" / "SKILL.md").exists()
        assert (tmp_path / ".cursor" / "rules" / "design-graph-ui-context.mdc").exists()
        assert (tmp_path / "AGENTS.md").exists()
        assert (tmp_path / ".agents" / "rules" / "design-graph-ui-context.md").exists()
        assert (tmp_path / ".kiro" / "steering" / "design-graph-ui-context.md").exists()

    def test_rerun_without_changes_is_idempotent(self, tmp_path, capsys):
        run_init_command(InitCliArgs(target=tmp_path, tools=("claude",)))
        code = run_init_command(InitCliArgs(target=tmp_path, tools=("claude",)))
        assert code == 0
        assert "já atualizado" in capsys.readouterr().out

    def test_refuses_to_overwrite_modified_copy_without_force(self, tmp_path, capsys):
        run_init_command(InitCliArgs(target=tmp_path, tools=("claude",)))
        dest = tmp_path / ".claude" / "skills" / "design-graph-ui-context" / "SKILL.md"
        dest.write_text("custom edit", encoding="utf-8")

        code = run_init_command(InitCliArgs(target=tmp_path, tools=("claude",)))

        assert code == 1
        assert dest.read_text(encoding="utf-8") == "custom edit"
        assert "--force" in capsys.readouterr().out

    def test_force_overwrites_modified_copy(self, tmp_path):
        run_init_command(InitCliArgs(target=tmp_path, tools=("claude",)))
        dest = tmp_path / ".claude" / "skills" / "design-graph-ui-context" / "SKILL.md"
        dest.write_text("custom edit", encoding="utf-8")

        code = run_init_command(InitCliArgs(target=tmp_path, tools=("claude",), force=True))

        assert code == 0
        assert dest.read_text(encoding="utf-8") != "custom edit"

    def test_unknown_tool_key_reports_error(self, tmp_path, capsys):
        code = run_init_command(InitCliArgs(target=tmp_path, tools=("not-a-tool",)))
        assert code == 1
        assert "unknown tool" in capsys.readouterr().out.lower()

    def test_empty_tool_selection_does_nothing(self, tmp_path, capsys):
        code = run_init_command(InitCliArgs(target=tmp_path, tools=()))
        assert code == 0
        assert not (tmp_path / ".claude").exists()


class TestRunInitCommandInteractivePrompt:
    def test_prompts_and_installs_selected_numbers(self, tmp_path):
        code = run_init_command(InitCliArgs(target=tmp_path, tools=None), prompt=lambda _: "1,3")
        assert code == 0
        assert (tmp_path / ".claude" / "skills" / "design-graph-ui-context" / "SKILL.md").exists()
        assert (tmp_path / "AGENTS.md").exists()
        assert not (tmp_path / ".cursor").exists()

    def test_prompts_and_installs_all_via_letter(self, tmp_path):
        code = run_init_command(InitCliArgs(target=tmp_path, tools=None), prompt=lambda _: "a")
        assert code == 0
        for target in TARGETS:
            assert (tmp_path / target.relative_path).exists()

    def test_empty_answer_selects_nothing(self, tmp_path, capsys):
        code = run_init_command(InitCliArgs(target=tmp_path, tools=None), prompt=lambda _: "")
        assert code == 0
        assert "Nothing selected" in capsys.readouterr().out

    def test_non_interactive_stdin_reports_actionable_error(self, tmp_path, capsys):
        def _raise_eof(_: str) -> str:
            raise EOFError

        code = run_init_command(InitCliArgs(target=tmp_path, tools=None), prompt=_raise_eof)
        assert code == 1
        assert "--tool" in capsys.readouterr().out
