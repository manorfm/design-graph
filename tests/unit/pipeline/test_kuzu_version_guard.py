"""
Unit tests for the Kuzu version guard in pipeline/coordinator.py.

The guard emits a warning to stderr when the installed Kuzu version is older
than the minimum required (0.6) and proceeds with the build rather than failing.
This keeps the system operational on older installs while surfacing the risk.
"""

import sys
import types
from unittest.mock import patch

import pytest

from design_graph.pipeline.coordinator import (
    KUZU_MIN_VERSION,
    check_kuzu_version,
)


class TestKuzuVersionGuard:
    def test_kuzu_min_version_constant_is_tuple(self):
        assert isinstance(KUZU_MIN_VERSION, tuple)

    def test_kuzu_min_version_is_0_6_or_higher(self):
        assert KUZU_MIN_VERSION >= (0, 6)

    def test_no_warning_when_version_meets_minimum(self, capsys):
        check_kuzu_version("0.6.0")
        assert capsys.readouterr().err == ""

    def test_no_warning_on_higher_patch_version(self, capsys):
        check_kuzu_version("0.6.5")
        assert capsys.readouterr().err == ""

    def test_no_warning_on_higher_minor_version(self, capsys):
        check_kuzu_version("0.7.0")
        assert capsys.readouterr().err == ""

    def test_no_warning_on_major_version_1(self, capsys):
        check_kuzu_version("1.0.0")
        assert capsys.readouterr().err == ""

    def test_warning_emitted_when_below_minimum(self, capsys):
        check_kuzu_version("0.5.9")
        err = capsys.readouterr().err
        assert err != "", "Expected a warning for Kuzu < 0.6"

    def test_warning_contains_version_string(self, capsys):
        check_kuzu_version("0.4.0")
        err = capsys.readouterr().err
        assert "0.4.0" in err

    def test_warning_mentions_minimum_version(self, capsys):
        check_kuzu_version("0.5.0")
        err = capsys.readouterr().err
        assert "0.6" in err

    def test_warning_mentions_design_graph(self, capsys):
        check_kuzu_version("0.3.0")
        err = capsys.readouterr().err
        assert "design-graph" in err

    def test_does_not_raise_for_any_valid_version(self):
        for v in ("0.1.0", "0.5.9", "0.6.0", "1.2.3", "99.0.0"):
            check_kuzu_version(v)  # must not raise

    def test_handles_two_part_version_string(self, capsys):
        check_kuzu_version("0.5")
        # "0.5" < "0.6" — should warn
        err = capsys.readouterr().err
        assert err != ""

    def test_handles_four_part_version_string(self, capsys):
        check_kuzu_version("0.6.0.1")
        assert capsys.readouterr().err == ""
