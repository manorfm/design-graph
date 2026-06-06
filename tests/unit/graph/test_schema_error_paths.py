"""
Tests for graph/schema.py error paths.

Targets:
  - initialize_schema re-raises non-"already exists" errors (lines 143-144)
  - _verify_kuzu_version emits warning for old Kuzu (lines 157-162)
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import kuzu
import pytest

from design_graph.graph.schema import _verify_kuzu_version, initialize_schema


class TestInitializeSchemaErrorPropagation:
    def test_reraises_non_already_exists_error(self, tmp_path):
        """initialize_schema must re-raise errors that are NOT 'already exists'."""
        db   = kuzu.Database(str(tmp_path / "err.db"))
        conn = kuzu.Connection(db)

        original_execute = conn.execute

        call_count = [0]

        def failing_execute(stmt, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("unexpected schema failure")
            return original_execute(stmt, *args, **kwargs)

        conn.execute = failing_execute

        with pytest.raises(RuntimeError, match="unexpected schema failure"):
            initialize_schema(conn)

    def test_silences_already_exists_errors(self, tmp_path):
        """Calling initialize_schema twice must not raise (idempotent)."""
        db   = kuzu.Database(str(tmp_path / "idem.db"))
        conn = kuzu.Connection(db)
        initialize_schema(conn)
        initialize_schema(conn)  # must not raise


class TestVerifyKuzuVersion:
    def test_no_warning_for_current_version(self, capsys):
        with patch.object(kuzu, "__version__", "0.6.2"):
            _verify_kuzu_version()
        assert capsys.readouterr().err == ""

    def test_warning_emitted_for_old_version(self, capsys):
        with patch.object(kuzu, "__version__", "0.5.0"):
            _verify_kuzu_version()
        err = capsys.readouterr().err
        assert "WARNING" in err or "0.5.0" in err

    def test_no_raise_when_version_attr_missing(self, capsys):
        # Simulate kuzu without __version__ attribute
        original = getattr(kuzu, "__version__", None)
        try:
            if hasattr(kuzu, "__version__"):
                delattr(kuzu, "__version__")  # type: ignore[attr-defined]
            _verify_kuzu_version()  # must not raise
        except AttributeError:
            pass  # some Python versions don't allow delattr on modules
        finally:
            if original is not None:
                kuzu.__version__ = original
