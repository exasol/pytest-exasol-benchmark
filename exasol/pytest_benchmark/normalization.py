"""Normalization of pytest-benchmark JSON into cases for comparisons.

Each benchmark of a document becomes one `NormalizedCase`, keyed by its
pytest-benchmark ``fullname``, holding the statistics in `RETAINED_STATISTICS`.
Normalization works on one runner execution; aggregating the cases of several
runner executions is part of the comparison.  The raw document is not changed.
"""

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .artifact import (
    describe_identity,
    problems_error,
    validate_benchmark_document,
)
from .models import (
    NormalizedCase,
    RunnerExecution,
)


def _timing_problem(value: Any) -> str | None:
    """Why `value` is no valid timing in seconds, or ``None`` if it is one."""
    try:
        valid = (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value >= 0
        )
    except OverflowError:
        # An integer too large for a float.
        valid = False
    return None if valid else "not a finite non-negative number"


def _rounds_problem(value: Any) -> str | None:
    """Why `value` is no valid number of rounds, or ``None`` if it is one."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return "not a positive whole number"
    return None


# The statistics of a benchmark's ``stats`` object a normalized case holds, and
# the checks they have to pass.  The timings are per round, in seconds.
_CHECKS = {
    "median": _timing_problem,
    "min": _timing_problem,
    "max": _timing_problem,
    "mean": _timing_problem,
    "rounds": _rounds_problem,
}
RETAINED_STATISTICS = tuple(_CHECKS)


def _inconsistency(statistics: Mapping[str, Any]) -> str | None:
    """
    Describe how the valid timings in `statistics` contradict each other.

    The median and the mean of the rounds have to lie between their minimum and
    maximum.  Returns ``None`` if they do, or if a timing is missing.
    """
    if not {"median", "min", "max", "mean"} <= statistics.keys():
        return None
    low, high = statistics["min"], statistics["max"]
    if low <= statistics["median"] <= high and low <= statistics["mean"] <= high:
        return None
    return (
        ", ".join(
            f"'stats.{name}' {statistics[name]!r}"
            for name in ("min", "median", "mean", "max")
        )
        + ", but the median and the mean have to lie between the minimum and"
        " the maximum"
    )


def _statistics(
    benchmark: Mapping[str, Any], source: str | Path, problems: list[str]
) -> dict[str, Any]:
    """
    Extract the `RETAINED_STATISTICS` of `benchmark` from the document `source`.

    Every missing, invalid or inconsistent statistic is appended to `problems`.
    """
    fullname = benchmark["fullname"]
    stats = benchmark.get("stats")
    if not isinstance(stats, Mapping):
        problems.append(f"{source} has no 'stats' object for benchmark {fullname!r}")
        return {}
    statistics = {}
    for name, check in _CHECKS.items():
        if name not in stats:
            problems.append(
                f"{source} has no 'stats.{name}' for benchmark {fullname!r}"
            )
            continue
        value = stats[name]
        if problem := check(value):
            problems.append(
                f"{source} has 'stats.{name}' {value!r} for benchmark"
                f" {fullname!r}, which is {problem}"
            )
        else:
            statistics[name] = value
    if inconsistency := _inconsistency(statistics):
        problems.append(f"{source} has {inconsistency} for benchmark {fullname!r}")
    return statistics


def normalize_benchmark(
    document: dict[str, Any], source: str | Path
) -> dict[str, NormalizedCase]:
    """
    Normalize the pytest-benchmark JSON `document` read from `source`.

    Returns one `NormalizedCase` per benchmark, keyed by its ``fullname`` in
    document order, holding the `RETAINED_STATISTICS` of the benchmark.  All
    other values of the document are dropped.  `source` names the document in
    every error message, for example its path.

    Raises an `ArtifactError` if `document` is not structured like the output of
    ``pytest --benchmark-json``, see `BenchmarkDocument`, for example if it
    contains no benchmarks or a ``fullname`` twice.  Only a document passing
    this validation has its statistics checked: then the error lists every
    benchmark missing a retained statistic or holding an invalid one, and every
    benchmark whose median or mean does not lie between its minimum and maximum,
    one per line.
    """
    validate_benchmark_document(document, source)
    problems: list[str] = []
    statistics = {
        benchmark["fullname"]: _statistics(benchmark, source, problems)
        for benchmark in document["benchmarks"]
    }
    if problems:
        raise problems_error(problems)
    return {
        fullname: NormalizedCase(fullname=fullname, data=data)
        for fullname, data in statistics.items()
    }


def normalize_execution(execution: RunnerExecution) -> dict[str, NormalizedCase]:
    """
    Normalize the benchmark document of `execution`, see `normalize_benchmark`.

    Error messages name the runner execution identity of `execution`.
    """
    source = (
        "the benchmark JSON of runner execution"
        f" ({describe_identity(execution.manifest)})"
    )
    return normalize_benchmark(execution.benchmark, source)


__all__ = ["RETAINED_STATISTICS", "normalize_benchmark", "normalize_execution"]
