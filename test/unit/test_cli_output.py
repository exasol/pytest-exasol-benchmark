"""Unit tests for CLI presentation rendering."""

from pathlib import Path

import pytest

from exasol.pytest_benchmark.cli_output import (
    format_comparison_reports,
    format_store_result,
)
from exasol.pytest_benchmark.models import (
    ArtifactManifest,
    ComparisonReport,
    ComparisonResult,
    PlatformMetadata,
    RunnerExecution,
)
from exasol.pytest_benchmark.models import TestSetCollection as Collection


def _result(name: str, change: float, **outcome: bool) -> ComparisonResult:
    return ComparisonResult(
        fullname=name,
        baseline=1.0,
        candidate=1.0 + change / 100,
        change_percent=change,
        **outcome,
    )


def _report(**overrides) -> ComparisonReport:
    values = {
        "test_set_id": "tpch",
        "comparison_target": "main",
        "status": "compared",
        "threshold_percent": 10.0,
        "absolute_floor_seconds": 1e-3,
        "baseline_execution_ids": ["history"],
        "candidate_execution_ids": ["candidate"],
    }
    values.update(overrides)
    return ComparisonReport(**values)


def test_formats_all_comparison_outcomes():
    """Comparison output includes each outcome and unmatched benchmark section."""
    report = _report(
        results=[
            _result("test::slower", 20.0, regression=True),
            _result("test::faster", -20.0, speedup=True),
            _result("test::same", 0.0),
        ],
        candidate_only=["test::new"],
        baseline_only=["test::old"],
    )

    assert format_comparison_reports([report]) == [
        "Test set tpch of comparison target main: compared 1 history runner"
        " execution with 1 of the candidate",
        "  Regressions, slower by more than 10 %:",
        "      +20.0 %  1 s -> 1.2 s  test::slower",
        "  Suspicious speedups, faster by more than 10 %:",
        "      -20.0 %  1 s -> 0.8 s  test::faster",
        "  Within the tolerance:",
        "       +0.0 %  1 s -> 1 s  test::same",
        "  Only in the candidate:",
        "    test::new",
        "  Only in the history:",
        "    test::old",
        "Summary: 1 regression, 1 speedup, 1 within the tolerance, 1 benchmark only"
        " in the candidate, 1 benchmark only in the history",
    ]


@pytest.mark.parametrize(
    "status, execution_ids, expected",
    [
        (
            "missing_baseline",
            {"baseline_execution_ids": [], "candidate_execution_ids": ["run-1"]},
            "Test set tpch of comparison target main: not in the history, nothing"
            " compared (1 candidate runner execution)",
        ),
        (
            "missing_candidate",
            {"candidate_execution_ids": []},
            "Test set tpch of comparison target main: not in the candidate, nothing"
            " compared",
        ),
    ],
)
def test_formats_missing_comparison_side(status, execution_ids, expected):
    """Missing test-set sides use their concise one-line rendering."""
    assert (
        format_comparison_reports([_report(status=status, **execution_ids)])[0]
        == expected
    )


def test_formats_store_result():
    """Stored-history output includes its aggregate and runner identity."""
    collection = Collection(
        test_set_id="tpch",
        comparison_target="main",
        executions=[
            RunnerExecution(
                manifest=ArtifactManifest(
                    test_set_id="tpch",
                    comparison_target="main",
                    runner_execution_id="run-1",
                    source_revision="revision",
                    platform=PlatformMetadata(os="linux", architecture="x86_64"),
                ),
                benchmark={},
            )
        ],
    )

    assert format_store_result([collection], Path("history")) == [
        "Stored 1 runner execution of 1 test set in history",
        "  Test set tpch of comparison target main: run-1",
    ]
