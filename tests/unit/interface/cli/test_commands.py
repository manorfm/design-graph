"""The commands an installation puts on the PATH."""

from importlib.metadata import entry_points


def _commands() -> dict[str, str]:
    return {ep.name: ep.value for ep in entry_points(group="console_scripts") if ep.dist and ep.dist.name == "design-graph"}


def test_the_build_command_answers_to_its_full_name_and_to_dgr():
    commands = _commands()
    assert commands["design-graph"] == commands["dgr"] == "design_graph.interface.cli.build:main"


def test_the_query_and_mcp_commands_keep_their_names():
    assert {"design-query", "design-mcp"} <= set(_commands())
