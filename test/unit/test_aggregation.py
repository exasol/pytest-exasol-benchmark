import pytest

from exasol.pytest_benchmark.aggregation import aggregate_collection
from exasol.pytest_benchmark.artifact import ArtifactError

A = "test/bench.py::test_a"
B = "test/bench.py::test_b"


def test_aggregate_collection(add_runs, only_collection, artifacts):
    add_runs(
        artifacts,
        {
            "run-1": {A: 1.0, B: 4.0},
            "run-2": {A: 3.0, B: 6.0},
            "run-3": {A: 2.0, B: 9.0},
        },
    )
    collection = only_collection(artifacts)
    aggregated = aggregate_collection(collection)
    assert aggregated.executions == collection.executions
    assert aggregated.executions is not collection.executions
    assert collection.cases == {}
    assert {name: case.data for name, case in aggregated.cases.items()} == {
        A: {"median": 2.0, "executions": 3},
        B: {"median": 6.0, "executions": 3},
    }


def test_aggregate_collection_rejects_runners_with_different_benchmarks(
    add_runs, only_collection, artifacts
):
    add_runs(artifacts, {"run-1": {A: 1.0}, "run-2": {A: 1.0, B: 1.0}})
    collection = only_collection(artifacts)
    with pytest.raises(ArtifactError, match=r"^runner execution .*'run-1'.* hold: "):
        aggregate_collection(collection)


def test_aggregate_collection_rejects_invalid_statistics(
    add_runs, only_collection, artifacts
):
    add_runs(artifacts, {"run-1": {A: -1.0}})
    collection = only_collection(artifacts)
    with pytest.raises(ArtifactError, match=r"^the benchmark JSON .*'stats.median'"):
        aggregate_collection(collection)
