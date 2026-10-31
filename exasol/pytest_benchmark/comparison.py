"""Comparison of runner artifacts with the checked-out benchmark history.

The *candidate*, the runner executions of the current benchmark run, is
compared with the *baseline*, the history in the current checkout.  Each side
is reduced to one value per test set and benchmark: each runner execution
yields the median of the benchmark's round timings, and these runner medians
are combined into their median.  A benchmark of the candidate slower than the
baseline by more than a threshold is a regression, one faster by more than
the same tolerance a speedup.  Test sets and benchmarks present on one side only
are reported, but never classified as a regression.
"""

import math
from collections.abc import Iterable
from pathlib import Path

from .aggregation import (
    aggregate_into,
    case_median,
)
from .artifact import (
    collect_candidates,
    problems_error,
)
from .history import (
    DEFAULT_HISTORY_ROOT,
    load_history,
)
from .models import (
    ComparisonReport,
    ComparisonResult,
    ComparisonStatus,
    NormalizedCase,
    TestSetCollection,
)

DEFAULT_THRESHOLD_PERCENT = 10.0
DEFAULT_ABSOLUTE_FLOOR_SECONDS = 1e-3

# A (test set ID, comparison target) pair, naming one test set collection.
_TestSetKey = tuple[str, str]

# Relative tolerance of the threshold, so a change equal to the threshold is
# no regression nor speedup even if computing it was not exact, for example
# 2.0 -> 2.2.
_THRESHOLD_TOLERANCE = 1e-9


def _check_parameters(threshold_percent: float, absolute_floor_seconds: float) -> None:
    if not math.isfinite(threshold_percent) or threshold_percent < 0:
        raise ValueError(
            f"threshold_percent {threshold_percent} is not a finite non-negative"
            " number"
        )
    if not math.isfinite(absolute_floor_seconds) or absolute_floor_seconds <= 0:
        raise ValueError(
            "absolute_floor_seconds"
            f" {absolute_floor_seconds} is not a finite positive number"
        )


def _by_key(
    collections: Iterable[TestSetCollection], side: str, problems: list[str]
) -> dict[_TestSetKey, TestSetCollection]:
    """
    Aggregate `collections`, keyed by test set and comparison target.

    A collection without runner executions holds no test set, so it is left
    out, as if `collections` did not contain it.
    """
    seen: set[_TestSetKey] = set()
    aggregated: dict[_TestSetKey, TestSetCollection] = {}
    for collection in collections:
        key = (collection.test_set_id, collection.comparison_target)
        if key in seen:
            problems.append(
                f"{side}: test set {key[0]!r} of comparison target {key[1]!r}"
                " occurs twice"
            )
            continue
        seen.add(key)
        if collection.executions:
            aggregated[key] = aggregate_into(collection, f"{side}: ", problems)
    return aggregated


def _beyond(delta: float, allowed_delta: float) -> bool:
    """Whether `delta` exceeds `allowed_delta`, beyond rounding."""
    return delta > allowed_delta and not math.isclose(
        delta, allowed_delta, rel_tol=_THRESHOLD_TOLERANCE
    )


def _result(
    fullname: str,
    baseline: float,
    candidate: float,
    threshold_percent: float,
    absolute_floor_seconds: float,
) -> ComparisonResult:
    """
    Compare the aggregated medians of one benchmark.

    A difference in either direction is excessive only when it is larger than
    both the configured absolute floor and the relative threshold.  The
    percentage remains a raw value relative to the actual baseline; it is
    omitted when that calculation is undefined or non-finite.
    """
    absolute_change = candidate - baseline
    change: float | None = None
    if baseline:
        percentage = absolute_change / baseline * 100
        if math.isfinite(percentage):
            change = percentage
    allowed_delta = max(
        absolute_floor_seconds, baseline * (threshold_percent / 100)
    )
    return ComparisonResult(
        fullname=fullname,
        baseline=baseline,
        candidate=candidate,
        change_percent=change,
        regression=_beyond(absolute_change, allowed_delta),
        speedup=_beyond(-absolute_change, allowed_delta),
    )


def _execution_ids(collection: TestSetCollection | None) -> list[str]:
    if collection is None:
        return []
    return [x.manifest.runner_execution_id for x in collection.executions]


def _report(
    key: _TestSetKey,
    baseline: TestSetCollection | None,
    candidate: TestSetCollection | None,
    threshold_percent: float,
    absolute_floor_seconds: float,
) -> ComparisonReport:
    status: ComparisonStatus = "compared"
    baseline_cases: dict[str, NormalizedCase] = {}
    candidate_cases: dict[str, NormalizedCase] = {}
    if baseline is None:
        status = "missing_baseline"
    elif candidate is None:
        status = "missing_candidate"
    else:
        baseline_cases = baseline.cases
        candidate_cases = candidate.cases
    return ComparisonReport(
        test_set_id=key[0],
        comparison_target=key[1],
        status=status,
        threshold_percent=threshold_percent,
        absolute_floor_seconds=absolute_floor_seconds,
        baseline_execution_ids=_execution_ids(baseline),
        candidate_execution_ids=_execution_ids(candidate),
        baseline_only=[name for name in baseline_cases if name not in candidate_cases],
        candidate_only=[name for name in candidate_cases if name not in baseline_cases],
        results=[
            _result(
                name,
                case_median(baseline_cases[name]),
                case_median(case),
                threshold_percent,
                absolute_floor_seconds,
            )
            for name, case in candidate_cases.items()
            if name in baseline_cases
        ],
    )


def compare_collections(
    baseline: Iterable[TestSetCollection],
    candidate: Iterable[TestSetCollection],
    *,
    threshold_percent: float = DEFAULT_THRESHOLD_PERCENT,
    absolute_floor_seconds: float = DEFAULT_ABSOLUTE_FLOOR_SECONDS,
) -> list[ComparisonReport]:
    """
    Compare the `candidate` collections with the `baseline` collections.

    Collections are matched by test set and comparison target.  Each side of a
    test set is aggregated by
    :func:`~exasol.pytest_benchmark.aggregation.aggregate_collection`, and the
    benchmarks both
    sides hold are compared by their aggregated medians.  A benchmark is a
    regression if the candidate is slower than the baseline by more than
    `threshold_percent` percent and by more than `absolute_floor_seconds`.
    The allowed difference is the larger of the absolute floor and the
    percentage of the baseline.  A percentage is reported relative to the raw
    baseline, except that it is ``None`` when the baseline is zero or the
    calculation is non-finite.  A benchmark can likewise be a speedup when it
    is faster beyond that same limit.

    Returns one `ComparisonReport` per test set and comparison target of either
    side: those of the candidate in its order, then those of the baseline only.
    Benchmarks held by one side only, for example because they were added to
    or removed from the test set, are listed in the report.  A test set held by
    one side only, or without runner executions on the other side, is
    reported with the corresponding status.  Neither is a regression.  Runner
    executions are not matched across the sides, and their source revision,
    platform, and attributes are not compared.

    Raises a `ValueError` if `threshold_percent` is negative or
    `absolute_floor_seconds` not positive, or either is not finite.  Raises an
    `ArtifactError` listing every problem of both sides: a test set occurring
    twice in a side, a runner execution lacking a benchmark another runner
    execution of its test set holds, and a benchmark document which cannot be
    normalized.  Each problem is prefixed with ``history`` or ``candidate``.
    """
    _check_parameters(threshold_percent, absolute_floor_seconds)
    problems: list[str] = []
    baselines = _by_key(baseline, "history", problems)
    candidates = _by_key(candidate, "candidate", problems)
    if problems:
        raise problems_error(problems)
    keys = [*candidates, *(key for key in baselines if key not in candidates)]
    return [
        _report(
            key,
            baselines.get(key),
            candidates.get(key),
            threshold_percent,
            absolute_floor_seconds,
        )
        for key in keys
    ]


def compare_with_history(
    artifacts_dir: Path,
    history_root: Path = DEFAULT_HISTORY_ROOT,
    *,
    threshold_percent: float = DEFAULT_THRESHOLD_PERCENT,
    absolute_floor_seconds: float = DEFAULT_ABSOLUTE_FLOOR_SECONDS,
) -> list[ComparisonReport]:
    """
    Compare the runner artifacts in `artifacts_dir` with the history.

    The candidate is collected by
    :func:`~exasol.pytest_benchmark.artifact.collect_candidates`, the baseline
    is the history below `history_root` as checked out, loaded by
    :func:`~exasol.pytest_benchmark.history.load_history`.  Git is not
    consulted: the history of the current checkout is the baseline, whichever
    revision it was stored at.  Nothing is written.  See `compare_collections`
    for the comparison, its parameters, and its errors; the errors of
    collecting and loading are raised as well.
    """
    # compare_collections checks the parameters as well, but only after the
    # artifacts and the history were read.
    _check_parameters(threshold_percent, absolute_floor_seconds)
    candidate = collect_candidates(artifacts_dir)
    baseline = load_history(history_root)
    return compare_collections(
        baseline,
        candidate,
        threshold_percent=threshold_percent,
        absolute_floor_seconds=absolute_floor_seconds,
    )


__all__ = [
    "DEFAULT_ABSOLUTE_FLOOR_SECONDS",
    "DEFAULT_THRESHOLD_PERCENT",
    "compare_collections",
    "compare_with_history",
]
