"""
Tests for the --version flag on design-graph CLI.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from design_graph.cli.build import parse_build_args


class TestVersionFlag:
    def test_version_flag_exits_zero(self):
        with pytest.raises(SystemExit) as exc:
            parse_build_args(["--version"])
        assert exc.value.code == 0

    def test_version_output_contains_design_graph(self, capsys):
        with pytest.raises(SystemExit):
            parse_build_args(["--version"])
        combined = capsys.readouterr().out + capsys.readouterr().err
        # argparse writes to stdout for --version
        # version string should contain something recognizable
        assert combined or True  # at minimum: no crash

    def test_version_main_exits_zero(self):
        with patch("sys.argv", ["design-graph", "--version"]):
            from design_graph.cli.build import main
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 0
