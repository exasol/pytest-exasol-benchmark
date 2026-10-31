"""Unit tests for the CLI comparison workflow."""

# The module's intentionally private stages are the unit under test.
# pylint: disable=protected-access

from pathlib import Path

import pytest

from exasol.pytest_benchmark import cli_comparison
from exasol.pytest_benchmark.cli_errors import _CommandError
from exasol.pytest_benchmark.models import ComparisonReport


def _missing_baseline_report() -> ComparisonReport:
    return ComparisonReport(
        test_set_id="tpch",
        comparison_target="main",
        status="missing_baseline",
        threshold_percent=10.0,
        absolute_floor_seconds=1e-3,
        candidate_execution_ids=["candidate"],
    )


def test_run_comparison_removes_json_output_before_loading(tmp_path, monkeypatch):
    """A failed load cannot leave JSON output from an earlier comparison."""
    output = tmp_path / "reports.json"
    output.write_text("[]")

    def fail_load(*_args):
        assert not output.exists()
        raise _CommandError("failed to load")

    monkeypatch.setattr(cli_comparison, "_load_comparison_reports", fail_load)

    with pytest.raises(_CommandError, match="failed to load"):
        cli_comparison._run_comparison(
            tmp_path / "artifacts", tmp_path / "history", 10.0, output
        )


def test_load_comparison_reports_translates_file_system_errors(monkeypatch, tmp_path):
    """Filesystem errors from the comparison use the command failure status."""

    def fail(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied", "history/.store")

    monkeypatch.setattr(cli_comparison, "compare_with_history", fail)

    with pytest.raises(_CommandError, match="cannot compare: Permission denied"):
        cli_comparison._load_comparison_reports(tmp_path, tmp_path, 10.0)


def test_require_compared_reports_rejects_unmatched_history(tmp_path):
    """Comparison reports must contain at least one test set held by both sides."""
    with pytest.raises(_CommandError, match="holds none of the candidate"):
        cli_comparison._require_compared_reports(
            [_missing_baseline_report()], tmp_path / "history"
        )


def test_write_comparison_reports_translates_file_system_errors(monkeypatch, tmp_path):
    """A JSON write failure uses the command failure status."""

    def fail_write(_self, _data):
        raise PermissionError(13, "Permission denied", "reports.json")

    monkeypatch.setattr(Path, "write_bytes", fail_write)

    with pytest.raises(
        _CommandError, match="cannot write the reports: Permission denied"
    ):
        cli_comparison._write_comparison_reports([], tmp_path / "reports.json")
