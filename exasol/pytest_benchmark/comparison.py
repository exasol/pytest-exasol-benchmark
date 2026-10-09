"""Comparison of runner artifacts with the checked-out benchmark history.

The *candidate*, the runner executions of the current benchmark run, is
compared with the *baseline*, the history in the current checkout.  Each side
is reduced to one value per test set and benchmark: each runner execution
yields the median of the benchmark's round timings, and these runner medians
are combined into their median.  A benchmark of the candidate slower than the
baseline by more than a threshold is a regression.  Test sets and benchmarks present on one side only are reported,
but never classified as a regression.
"""

import math
import statistics
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import cast

from .artifact import (
    ArtifactError,
    collect_candidates,
    describe_identity,
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
from .normalization import normalize_execution

DEFAULT_THRESHOLD_PERCENT = 10.0
DEFAULT_NEAR_ZERO_SECONDS = 1e-3

# A (test set ID, comparison target) pair, naming one test set collection.
_Key = tuple[str, str]

# Relative tolerance of the threshold, so a change equal to the threshold is
# no regression even if computing it was not exact, for example 2.0 -> 2.2.
_THRESHOLD_TOLERANCE = 1e-9


def _median(case: NormalizedCase) -> float:
    """The median of `case`, a number checked by `normalize_execution`."""
    return cast(float, case.data["median"])


def _aggregate(
    collection: TestSetCollection, prefix: str, problems: list[str]
) -> TestSetCollection:
    """
    Aggregate the cases of the runner executions of `collection`.

    Returns a copy of `collection` with one case per benchmark.  Every problem
    is appended to `problems`, prefixed with `prefix`, which names the side of
    a comparison the collection belongs to; then the copy holds no cases.
    """
    normalized = []
    failed = False
    for execution in collection.executions:
        try:
            normalized.append((execution, normalize_execution(execution)))
        except ArtifactError as error:
            problems.extend(prefix + line for line in str(error).splitlines())
            failed = True
    fullnames = list(dict.fromkeys(name for _, cases in normalized for name in cases))
    for execution, cases in normalized:
        if missing := [name for name in fullnames if name not in cases]:
            problems.append(
                f"{prefix}runner execution ({describe_identity(execution.manifest)})"
                " lacks benchmarks which other runner executions of its test set"
                f" hold: {', '.join(missing)}"
            )
            failed = True
    cases = {}
    if not failed:
        cases = {
            name: NormalizedCase(
                fullname=name,
                data={
                    "median": statistics.median(
                        _median(execution_cases[name])
                        for _, execution_cases in normalized
                    ),
                    "executions": len(normalized),
                },
            )
            for name in fullnames
        }
    return collection.model_copy(
        update={"executions": list(collection.executions), "cases": cases}
    )


def aggregate_collection(collection: TestSetCollection) -> TestSetCollection:
    """
    Aggregate the cases of the runner executions of `collection`.

    Returns a copy of `collection` holding one `NormalizedCase` per benchmark,
    in the order the benchmarks first occur.  It holds the ``median`` of the
    median round timings of the runner executions, in seconds, and their
    number as ``executions``.  Cases `collection` already holds are replaced.

    All runner executions of a test set run the same benchmarks.  Raises an
    `ArtifactError` listing every runner execution which lacks a benchmark of
    another one, and the problems of every benchmark document which cannot be
    normalized, see `normalize_execution`.
    """
    problems: list[str] = []
    aggregated = _aggregate(collection, "", problems)
    if problems:
        raise problems_error(problems)
    return aggregated


def _check_parameters(threshold_percent: float, near_zero_seconds: float) -> None:
    if not math.isfinite(threshold_percent) or threshold_percent < 0:
        raise ValueError(
            f"threshold_percent {threshold_percent} is not a finite non-negative"
            " number"
        )
    if not math.isfinite(near_zero_seconds) or near_zero_seconds <= 0:
        raise ValueError(
            f"near_zero_seconds {near_zero_seconds} is not a finite positive number"
        )


def _by_key(
    collections: Iterable[TestSetCollection], side: str, problems: list[str]
) -> dict[_Key, TestSetCollection]:
    """
    Aggregate `collections`, keyed by test set and comparison target.

    A collection without runner executions holds no test set, so it is left
    out, as if `collections` did not contain it.
    """
    seen: set[_Key] = set()
    aggregated: dict[_Key, TestSetCollection] = {}
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
            aggregated[key] = _aggregate(collection, f"{side}: ", problems)
    return aggregated


def _result(
    fullname: str,
    baseline: float,
    candidate: float,
    threshold_percent: float,
    near_zero_seconds: float,
) -> ComparisonResult:
    """
    Compare the aggregated medians of one benchmark.

    The change is relative to the baseline, but at least to
    `near_zero_seconds`, and limited to the largest float rather than
    overflowing.  It is reported only if the baseline is greater than
    `near_zero_seconds`: a percentage of a timing that close to zero is
    meaningless.
    """
    reference = max(baseline, near_zero_seconds)
    change = min((candidate - reference) / reference * 100, sys.float_info.max)
    return ComparisonResult(
        fullname=fullname,
        baseline=baseline,
        candidate=candidate,
        change_percent=change if baseline > near_zero_seconds else None,
        regression=change > threshold_percent
        and not math.isclose(change, threshold_percent, rel_tol=_THRESHOLD_TOLERANCE),
    )


def _execution_ids(collection: TestSetCollection | None) -> list[str]:
    if collection is None:
        return []
    return [x.manifest.runner_execution_id for x in collection.executions]


def _report(
    key: _Key,
    baseline: TestSetCollection | None,
    candidate: TestSetCollection | None,
    threshold_percent: float,
    near_zero_seconds: float,
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
        near_zero_seconds=near_zero_seconds,
        baseline_execution_ids=_execution_ids(baseline),
        candidate_execution_ids=_execution_ids(candidate),
        baseline_only=[name for name in baseline_cases if name not in candidate_cases],
        candidate_only=[name for name in candidate_cases if name not in baseline_cases],
        results=[
            _result(
                name,
                _median(baseline_cases[name]),
                _median(case),
                threshold_percent,
                near_zero_seconds,
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
    near_zero_seconds: float = DEFAULT_NEAR_ZERO_SECONDS,
) -> list[ComparisonReport]:
    """
    Compare the `candidate` collections with the `baseline` collections.

    Collections are matched by test set and comparison target.  Each side of a
    test set is aggregated by `aggregate_collection`, and the benchmarks both
    sides hold are compared by their aggregated medians.  A benchmark is a
    regression if the candidate is slower than the baseline by more than
    `threshold_percent` percent.  A baseline not greater than
    `near_zero_seconds` is too close to zero for a meaningful percentage: the
    benchmark is compared as if the baseline was `near_zero_seconds`, and its
    change is ``None``.  So a candidate not slower than `near_zero_seconds` is
    never a regression.

    Returns one `ComparisonReport` per test set and comparison target of either
    side: those of the candidate in its order, then those of the baseline only.
    Benchmarks held by one side only, for example because they were added to
    or removed from the test set, are listed in the report.  A test set held by
    one side only, or without runner executions on the other side, is
    reported with the corresponding status.  Neither is a regression.  Runner executions are not matched across the sides, and
    their source revision, platform, and attributes are not compared.

    Raises a `ValueError` if `threshold_percent` is negative or
    `near_zero_seconds` not positive, or either is not finite.  Raises an
    `ArtifactError` listing every problem of both sides: a test set occurring
    twice in a side, a runner execution lacking a benchmark another runner
    execution of its test set holds, and a benchmark document which cannot be
    normalized.  Each problem is prefixed with ``history`` or ``candidate``.
    """
    _check_parameters(threshold_percent, near_zero_seconds)
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
            near_zero_seconds,
        )
        for key in keys
    ]


def compare_with_history(
    artifacts_dir: Path,
    history_root: Path = DEFAULT_HISTORY_ROOT,
    *,
    threshold_percent: float = DEFAULT_THRESHOLD_PERCENT,
    near_zero_seconds: float = DEFAULT_NEAR_ZERO_SECONDS,
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
    _check_parameters(threshold_percent, near_zero_seconds)
    candidate = collect_candidates(artifacts_dir)
    baseline = load_history(history_root)
    return compare_collections(
        baseline,
        candidate,
        threshold_percent=threshold_percent,
        near_zero_seconds=near_zero_seconds,
    )


__all__ = [
    "DEFAULT_NEAR_ZERO_SECONDS",
    "DEFAULT_THRESHOLD_PERCENT",
    "aggregate_collection",
    "compare_collections",
    "compare_with_history",
]
