"""Text rendering for the benchmark command-line interface."""

from pathlib import Path

from .models import (
    ComparisonReport,
    ComparisonResult,
    TestSetCollection,
)


def _plural(count: int, noun: str) -> str:
    """`count` followed by `noun`, pluralized unless `count` is one."""
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _seconds(value: float) -> str:
    """A timing in seconds, rounded to four significant digits."""
    return f"{value:.4g} s"


def _format_result(result: ComparisonResult) -> str:
    """One indented line describing a compared benchmark."""
    text = "n/a" if result.change_percent is None else f"{result.change_percent:+.1f} %"
    return (
        f"    {text:>9}  {_seconds(result.baseline)} ->"
        f" {_seconds(result.candidate)}  {result.fullname}"
    )


def _format_report(report: ComparisonReport) -> list[str]:
    """The lines describing one comparison report."""
    name = (
        f"Test set {report.test_set_id} of comparison target"
        f" {report.comparison_target}"
    )
    baseline_ids = report.baseline_execution_ids
    candidate_ids = report.candidate_execution_ids
    if report.status == "missing_baseline":
        return [
            f"{name}: not in the history, nothing compared"
            f" ({_plural(len(candidate_ids), 'candidate runner execution')})"
        ]
    if report.status == "missing_candidate":
        return [f"{name}: not in the candidate, nothing compared"]
    lines = [
        f"{name}: compared"
        f" {_plural(len(baseline_ids), 'history runner execution')}"
        f" with {len(candidate_ids)} of the candidate"
    ]
    threshold = f"{report.threshold_percent:g} %"
    within = [r for r in report.results if not (r.regression or r.speedup)]
    for title, results in (
        (f"Regressions, slower by more than {threshold}:", report.regressions),
        (f"Suspicious speedups, faster by more than {threshold}:", report.speedups),
        ("Within the tolerance:", within),
    ):
        if results:
            lines.append(f"  {title}")
            lines.extend(_format_result(result) for result in results)
    for title, fullnames in (
        ("Only in the candidate:", report.candidate_only),
        ("Only in the history:", report.baseline_only),
    ):
        if fullnames:
            lines.append(f"  {title}")
            lines.extend(f"    {fullname}" for fullname in fullnames)
    return lines


def _summary(reports: list[ComparisonReport]) -> str:
    """One line counting all comparison outcomes."""

    def count(attribute: str) -> int:
        return sum(len(getattr(report, attribute)) for report in reports)

    def status(value: str) -> int:
        return sum(report.status == value for report in reports)

    regressions = count("regressions")
    speedups = count("speedups")
    parts = [
        _plural(regressions, "regression"),
        _plural(speedups, "speedup"),
        f"{count('results') - regressions - speedups} within the tolerance",
    ]
    for number, text in (
        (count("candidate_only"), "only in the candidate"),
        (count("baseline_only"), "only in the history"),
    ):
        if number:
            parts.append(f"{_plural(number, 'benchmark')} {text}")
    for number, text in (
        (status("missing_baseline"), "not in the history"),
        (status("missing_candidate"), "not in the candidate"),
    ):
        if number:
            parts.append(f"{_plural(number, 'test set')} {text}")
    return "Summary: " + ", ".join(parts)


def format_comparison_reports(reports: list[ComparisonReport]) -> list[str]:
    """All report lines followed by their summary."""
    return [
        *(line for report in reports for line in _format_report(report)),
        _summary(reports),
    ]


def format_store_result(
    collections: list[TestSetCollection], history_root: Path
) -> list[str]:
    """The lines printed after storing benchmark history."""
    executions = sum(len(collection.executions) for collection in collections)
    lines = [
        f"Stored {_plural(executions, 'runner execution')} of"
        f" {_plural(len(collections), 'test set')} in {history_root}"
    ]
    lines.extend(
        f"  Test set {collection.test_set_id} of comparison target"
        f" {collection.comparison_target}: "
        + ", ".join(x.manifest.runner_execution_id for x in collection.executions)
        for collection in collections
    )
    return lines
