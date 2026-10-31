"""Comparison workflow used by the benchmark command-line interface."""

from pathlib import Path

from pydantic import TypeAdapter

from .artifact import (
    ArtifactError,
    _os_message,
)
from .cli_errors import _CommandError
from .comparison import compare_with_history
from .models import ComparisonReport

_REPORTS = TypeAdapter(list[ComparisonReport])


def _remove_previous_reports(json_output: Path) -> None:
    """Remove an earlier JSON report before starting a comparison."""
    try:
        json_output.unlink(missing_ok=True)
    except OSError as error:
        raise _CommandError(
            f"cannot remove earlier reports: {_os_message(error)}"
        ) from error


def _load_comparison_reports(
    artifacts_dir: Path,
    history_root: Path,
    threshold: float,
) -> list[ComparisonReport]:
    """Load reports and translate comparison errors for the command line."""
    try:
        return compare_with_history(
            artifacts_dir, history_root, threshold_percent=threshold
        )
    except ArtifactError as error:
        raise _CommandError(str(error)) from error
    except OSError as error:
        # Not every file system error is reported as an ArtifactError, and exit
        # status 1 would report it as a regression.
        raise _CommandError(f"cannot compare: {_os_message(error)}") from error


def _require_compared_reports(
    reports: list[ComparisonReport], history_root: Path
) -> None:
    """Reject reports which do not compare a test set held by both sides."""
    if not any(report.status == "compared" for report in reports):
        # Without a compared test set nothing can exceed the tolerance, so passing
        # would hide a mistyped --history-root, test set ID, or comparison
        # target, or a checkout without the history.
        raise _CommandError(
            f"the history in {history_root} holds none of the candidate's test"
            " sets, so nothing can be compared.  Check --history-root and the"
            " test set IDs and comparison targets of the artifacts, or store a"
            " benchmark run as the history first, see the store command"
        )


def _write_comparison_reports(
    reports: list[ComparisonReport], json_output: Path
) -> None:
    """Write reports as formatted JSON and translate filesystem errors."""
    try:
        json_output.write_bytes(_REPORTS.dump_json(reports, indent=2) + b"\n")
    except OSError as error:
        raise _CommandError(
            f"cannot write the reports: {_os_message(error)}"
        ) from error


def _run_comparison(
    artifacts_dir: Path,
    history_root: Path,
    threshold: float,
    json_output: Path | None,
) -> list[ComparisonReport]:
    """Compare, validate, and optionally serialize runner-artifact reports."""
    if json_output is not None:
        # A failed comparison must not leave the reports of an earlier one.
        _remove_previous_reports(json_output)
    reports = _load_comparison_reports(artifacts_dir, history_root, threshold)
    _require_compared_reports(reports, history_root)
    if json_output is not None:
        _write_comparison_reports(reports, json_output)
    return reports
