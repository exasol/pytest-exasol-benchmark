"""Aggregation of the runner executions of a test set.

The runner executions of a test set sample the same benchmarks.  They are
reduced to one value per benchmark: each runner execution yields the median of
the benchmark's round timings, and these runner medians are combined into
their median.
"""

import statistics
from typing import cast

from .artifact import (
    ArtifactError,
    describe_identity,
    problems_error,
)
from .models import (
    NormalizedCase,
    TestSetCollection,
)
from .normalization import normalize_execution


def case_median(case: NormalizedCase) -> float:
    """The median of `case`, a number checked by `normalize_execution`."""
    return cast(float, case.data["median"])


def aggregate_into(
    collection: TestSetCollection, err_prefix: str, problems: list[str]
) -> TestSetCollection:
    """
    Aggregate the cases of the runner executions of `collection`.

    All or nothing: if any runner execution has a problem, no benchmark is
    aggregated, and the returned copy of `collection` holds no cases at all.
    Otherwise it holds one case per benchmark.

    Problems are collected rather than raised, so the caller can report those
    of all collections at once.  Each one is appended to `problems`, prefixed
    with `err_prefix`.  The caller raises if `problems` is not empty
    afterwards, so a copy without cases is never used.
    """
    normalized = []
    failed = False
    for execution in collection.executions:
        try:
            normalized.append((execution, normalize_execution(execution)))
        except ArtifactError as error:
            problems.extend(err_prefix + line for line in str(error).splitlines())
            failed = True
    fullnames = list(dict.fromkeys(name for _, cases in normalized for name in cases))
    for execution, cases in normalized:
        if missing := [name for name in fullnames if name not in cases]:
            problems.append(
                f"{err_prefix}runner execution"
                f" ({describe_identity(execution.manifest)})"
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
                        case_median(execution_cases[name])
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
    aggregated = aggregate_into(collection, "", problems)
    if problems:
        raise problems_error(problems)
    return aggregated


__all__ = ["aggregate_collection"]
