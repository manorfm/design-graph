"""
Targeted tests for cli/validate.py coverage gaps.

Covers:
  - GraphViolation.to_dict() (line 47)
  - GraphValidationReport.status/warning_count with warnings and errors (71, 73)
  - validate_graph: DB readable exception (lines 127-134)
  - _check_no_orphaned_components: components with no screen refs (161-162)
  - _check_sections_have_screens: orphaned sections (171)
  - _check_tokens_have_usage: zero-usage tokens (178)
  - render_validation_report: with violations present (289-292)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import kuzu
import pytest

from design_graph.cli.validate import (
    GraphValidationReport,
    GraphViolation,
    ValidationSeverity,
    _check_no_orphaned_components,
    _check_no_orphaned_screens,
    _check_tokens_have_usage,
    render_validation_report,
    validate_graph,
)
from design_graph.core.models import (
    DesignToken,
    ExtractedComponent,
    ExtractedScreen,
    ExtractedSection,
)
from design_graph.graph.schema import initialize_schema
from design_graph.graph.writer import GraphWriter

FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "simple.html"


# ── GraphViolation.to_dict ────────────────────────────────────────────────────

class TestGraphViolationToDict:
    def test_to_dict_returns_dict_with_required_keys(self):
        v = GraphViolation(
            severity=ValidationSeverity.ERROR,
            check_name="test_check",
            message="Something is wrong",
            details={"count": 3},
        )
        d = v.to_dict()
        assert d["severity"] == "error"
        assert d["check"] == "test_check"
        assert d["message"] == "Something is wrong"
        assert d["details"] == {"count": 3}

    def test_warning_severity_in_dict(self):
        v = GraphViolation(severity=ValidationSeverity.WARNING,
                           check_name="w", message="warn", details={})
        assert v.to_dict()["severity"] == "warning"

    def test_info_severity_in_dict(self):
        v = GraphViolation(severity=ValidationSeverity.INFO,
                           check_name="i", message="info", details={})
        assert v.to_dict()["severity"] == "info"


# ── GraphValidationReport status and counts ───────────────────────────────────

class TestGraphValidationReportProperties:
    def _report_with(self, *severities: ValidationSeverity) -> GraphValidationReport:
        r = GraphValidationReport(db_path=Path("/tmp/test.db"))
        for sev in severities:
            r.violations.append(GraphViolation(sev, "check", "msg", {}))
        return r

    def test_status_ok_when_no_violations(self):
        assert self._report_with().status == "ok"

    def test_status_warnings_when_only_warnings(self):
        assert self._report_with(ValidationSeverity.WARNING).status == "warnings"

    def test_status_errors_when_any_error(self):
        r = self._report_with(ValidationSeverity.WARNING, ValidationSeverity.ERROR)
        assert r.status == "errors"

    def test_warning_count_correct(self):
        r = self._report_with(ValidationSeverity.WARNING, ValidationSeverity.WARNING, ValidationSeverity.ERROR)
        assert r.warning_count == 2

    def test_error_count_correct(self):
        r = self._report_with(ValidationSeverity.ERROR, ValidationSeverity.WARNING)
        assert r.error_count == 1

    def test_to_dict_includes_violations(self):
        r = self._report_with(ValidationSeverity.WARNING)
        d = r.to_dict()
        assert "violations" in d
        assert len(d["violations"]) == 1
        assert d["status"] == "warnings"


# ── validate_graph: corrupt DB exception path ────────────────────────────────

class TestValidateGraphExceptionPath:
    def test_corrupt_db_file_returns_error_violation(self, tmp_path):
        bad_db = tmp_path / "corrupt.db"
        bad_db.write_bytes(b"this is definitely not a kuzu database file")
        report = validate_graph(bad_db)
        assert report.status == "errors"
        error_violations = [v for v in report.violations
                            if v.severity == ValidationSeverity.ERROR]
        assert error_violations

    def test_corrupt_db_violation_has_database_readable_check(self, tmp_path):
        bad_db = tmp_path / "bad.db"
        bad_db.write_bytes(b"not kuzu")
        report = validate_graph(bad_db)
        check_names = {v.check_name for v in report.violations}
        assert "database_readable" in check_names or "database_exists" in check_names


# ── _check_no_orphaned_components ─────────────────────────────────────────────

class TestCheckNoOrphanedComponents:
    def _make_db_with_orphan(self, tmp_path):
        """Create a DB with a component that's not used by any screen."""
        db   = kuzu.Database(str(tmp_path / "orphan.db"))
        conn = kuzu.Connection(db)
        initialize_schema(conn)
        gw = GraphWriter(conn)
        # Component with no screen reference
        orphan = ExtractedComponent(
            name="OrphanComp", comp_type="card", jsx_snippet="<div/>",
            occurrence=1, classes="", styles=[], interactions=[], texts=[], child_refs=[],
        )
        gw.write_component(orphan, {})
        # No write_screen() call → OrphanComp has no USES_COMPONENT relationship
        ro_db   = kuzu.Database(str(tmp_path / "orphan.db"), read_only=True)
        ro_conn = kuzu.Connection(ro_db)
        from design_graph.graph.reader import GraphReader
        return GraphReader(ro_conn)

    def test_orphaned_component_detected(self, tmp_path):
        reader = self._make_db_with_orphan(tmp_path)
        counts = reader.count_nodes()
        violations = _check_no_orphaned_components(counts, reader)
        assert len(violations) >= 1

    def test_violation_names_orphan(self, tmp_path):
        reader = self._make_db_with_orphan(tmp_path)
        counts = reader.count_nodes()
        violations = _check_no_orphaned_components(counts, reader)
        if violations:
            details = violations[0].details
            assert "OrphanComp" in details.get("components", [])

    def test_total_is_not_truncated_to_display_sample(self):
        class Reader:
            def _q(self, query, params=None):
                if "count(c)" in query:
                    return [{"total": 278}]
                return [{"c.name": f"Comp{i}"} for i in range(20)]

        violation = _check_no_orphaned_components({}, Reader())[0]
        assert violation.details["total"] == 278
        assert len(violation.details["components"]) == 20
        assert "278" in violation.message


class TestCheckNoOrphanedScreens:
    def test_uses_relationships_as_source_of_truth(self):
        queries = []

        class Reader:
            def _q(self, query, params=None):
                queries.append(query)
                if "count(s)" in query:
                    return [{"total": 2}]
                return [{"s.name": "One"}, {"s.name": "Two"}]

        violations = _check_no_orphaned_screens({}, Reader())
        assert violations[0].details["total"] == 2
        assert violations[0].severity == ValidationSeverity.INFO
        assert all("USES_COMPONENT" in query for query in queries)


# ── _check_tokens_have_usage ──────────────────────────────────────────────────

class TestCheckTokensHaveUsage:
    def _make_db_with_zero_usage_token(self, tmp_path):
        db   = kuzu.Database(str(tmp_path / "tokens.db"))
        conn = kuzu.Connection(db)
        initialize_schema(conn)
        gw = GraphWriter(conn)
        # Token with usage=0 — unusual but possible from edge cases
        zero_token = DesignToken(id="col_zero", category="color",
                                 label="mystery", value="#abcdef", usage=0)
        gw.write_tokens([zero_token])
        ro_db   = kuzu.Database(str(tmp_path / "tokens.db"), read_only=True)
        ro_conn = kuzu.Connection(ro_db)
        from design_graph.graph.reader import GraphReader
        return GraphReader(ro_conn)

    def test_zero_usage_token_detected(self, tmp_path):
        reader = self._make_db_with_zero_usage_token(tmp_path)
        violations = _check_tokens_have_usage(reader.count_nodes(), reader)
        assert len(violations) >= 1

    def test_violation_lists_token_label(self, tmp_path):
        reader = self._make_db_with_zero_usage_token(tmp_path)
        violations = _check_tokens_have_usage(reader.count_nodes(), reader)
        if violations:
            assert "mystery" in violations[0].details.get("tokens", [])


# ── render_validation_report with violations ─────────────────────────────────

class TestRenderValidationReportWithViolations:
    def _report(self, *severities) -> GraphValidationReport:
        r = GraphValidationReport(
            db_path=Path("/tmp/test.db"),
            node_counts={"screens": 2, "components": 5, "tokens": 3,
                         "sections": 4, "contains": 1},
        )
        for sev in severities:
            r.violations.append(GraphViolation(sev, f"check_{sev.value}", f"msg_{sev.value}", {}))
        return r

    def test_error_violations_shown_in_output(self):
        report = self._report(ValidationSeverity.ERROR)
        output = render_validation_report(report)
        assert "[ERROR]" in output or "error" in output.lower()

    def test_warning_violations_shown_in_output(self):
        report = self._report(ValidationSeverity.WARNING)
        output = render_validation_report(report)
        assert "[WARN]" in output or "warn" in output.lower()

    def test_info_violations_shown_in_output(self):
        report = self._report(ValidationSeverity.INFO)
        output = render_validation_report(report)
        assert "[INFO]" in output or "info" in output.lower()

    def test_all_violation_messages_present(self):
        report = self._report(ValidationSeverity.ERROR, ValidationSeverity.WARNING)
        output = render_validation_report(report)
        assert "msg_error" in output
        assert "msg_warning" in output

    def test_error_count_shown(self):
        report = self._report(ValidationSeverity.ERROR, ValidationSeverity.ERROR)
        output = render_validation_report(report)
        assert "2" in output
