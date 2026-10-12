import hashlib
import math
import sys
from pathlib import Path

import pytest

from exasol.pytest_benchmark.artifact import (
    ArtifactError,
    collect_candidates,
)
from exasol.pytest_benchmark.comparison import (
    DEFAULT_NEAR_ZERO_SECONDS,
    DEFAULT_THRESHOLD_PERCENT,
    aggregate_collection,
    compare_collections,
    compare_with_history,
)
from exasol.pytest_benchmark.history import store_history
from exasol.pytest_benchmark.models import ComparisonReport
from exasol.pytest_benchmark.models import TestSetCollection as Collection

A = "test/bench.py::test_a"
B = "test/bench.py::test_b"


@pytest.fixture
def history_root(tmp_path) -> Path:
    return tmp_path / "benchmark-history"


@pytest.fixture
def add_runs(make_bundle):
    """Package one runner artifact per runner execution ID in *runs*.

    *runs* maps each runner execution ID to the medians of its benchmarks.
    """

    def add(directory: Path, runs, test_set_id="tpch", source_revision="d66cb7d"):
        for runner, medians in runs.items():
            make_bundle(
                directory,
                f"{test_set_id}-{runner}",
                test_set_id=test_set_id,
                runner_execution_id=runner,
                source_revision=source_revision,
                medians=medians,
            )

    return add


@pytest.fixture
def store(tmp_path, add_runs, history_root):
    """Store the runner executions in *runs* as the history, see `add_runs`."""

    def store_runs(runs, test_set_id="tpch", source_revision="1208d17"):
        stored = tmp_path / f"stored-{test_set_id}"
        add_runs(stored, runs, test_set_id, source_revision)
        store_history(stored, history_root)

    return store_runs


@pytest.fixture
def compare(artifacts, history_root):
    def run(**kwargs) -> list[ComparisonReport]:
        return compare_with_history(artifacts, history_root, **kwargs)

    return run


def only(reports: list[ComparisonReport]) -> ComparisonReport:
    assert len(reports) == 1
    return reports[0]


def only_collection(artifacts):
    (collection,) = collect_candidates(artifacts)
    return collection


def results(report: ComparisonReport) -> dict[str, tuple[float, bool]]:
    return {r.fullname: (r.change_percent, r.regression) for r in report.results}


def test_defaults():
    assert DEFAULT_THRESHOLD_PERCENT == 10.0
    assert DEFAULT_NEAR_ZERO_SECONDS == 1e-3


def test_compares_aggregated_medians(store, add_runs, artifacts, compare):
    store({"run-1": {A: 10.0, B: 2.0}})
    add_runs(artifacts, {"run-1": {A: 12.0, B: 1.0}})
    report = only(compare())
    assert report.status == "compared"
    assert (report.test_set_id, report.comparison_target) == ("tpch", "main")
    assert report.baseline_execution_ids == ["run-1"]
    assert report.candidate_execution_ids == ["run-1"]
    assert results(report) == {A: (20.0, True), B: (-50.0, False)}
    assert [r.fullname for r in report.regressions] == [A]
    assert (report.results[0].baseline, report.results[0].candidate) == (10.0, 12.0)


@pytest.mark.parametrize(
    "candidate, threshold, regression",
    [
        pytest.param(11.0, DEFAULT_THRESHOLD_PERCENT, False, id="at-default"),
        # (2.2 - 2.0) / 2.0 * 100 computes as 10.000000000000009.
        pytest.param(2.2, DEFAULT_THRESHOLD_PERCENT, False, id="at-default-inexact"),
        pytest.param(11.5, DEFAULT_THRESHOLD_PERCENT, True, id="above-default"),
        pytest.param(10.5, DEFAULT_THRESHOLD_PERCENT, False, id="below-default"),
        pytest.param(10.0, 0.0, False, id="unchanged-at-zero"),
        pytest.param(11.5, 20.0, False, id="below-custom"),
        pytest.param(12.5, 20.0, True, id="above-custom"),
    ],
)
def test_threshold(
    store, add_runs, artifacts, compare, candidate, threshold, regression
):
    baseline = 2.0 if candidate == 2.2 else 10.0
    store({"run-1": {A: baseline}})
    add_runs(artifacts, {"run-1": {A: candidate}})
    report = only(compare(threshold_percent=threshold))
    assert report.threshold_percent == threshold
    assert report.results[0].regression is regression
    assert report.regressions == ([report.results[0]] if regression else [])


def test_median_over_runners_with_different_counts(store, add_runs, artifacts, compare):
    store({"run-1": {A: 10.0}, "run-2": {A: 30.0}, "run-3": {A: 20.0}})
    add_runs(
        artifacts,
        {"run-1": {A: 21.0}, "run-2": {A: 23.0}, "run-3": {A: 99.0}, "run-4": {A: 1.0}},
    )
    report = only(compare())
    assert (report.results[0].baseline, report.results[0].candidate) == (20.0, 22.0)
    assert report.candidate_execution_ids == ["run-1", "run-2", "run-3", "run-4"]
    assert results(report) == {A: (10.0, False)}


def test_missing_baseline(store, add_runs, artifacts, compare):
    store({"run-1": {A: 10.0}}, test_set_id="other")
    add_runs(artifacts, {"run-1": {A: 99.0}})
    reports = compare()
    assert [(r.test_set_id, r.status) for r in reports] == [
        ("tpch", "missing_baseline"),
        ("other", "missing_candidate"),
    ]
    assert not any(r.results for r in reports)
    assert reports[0].candidate_execution_ids == ["run-1"]
    assert reports[1].baseline_execution_ids == ["run-1"]


def test_missing_history(add_runs, artifacts, compare, history_root):
    add_runs(artifacts, {"run-1": {A: 10.0}})
    assert only(compare()).status == "missing_baseline"
    assert not history_root.exists()


def test_compares_benchmarks_both_sides_hold(store, add_runs, artifacts, compare):
    # test_a was removed from the test set and test_c added; test_b is slower.
    store({"run-1": {A: 10.0, B: 10.0}})
    add_runs(artifacts, {"run-1": {B: 20.0, "test/bench.py::test_c": 99.0}})
    report = only(compare())
    assert report.status == "compared"
    assert report.baseline_only == [A]
    assert report.candidate_only == ["test/bench.py::test_c"]
    assert results(report) == {B: (100.0, True)}


def test_reports_no_common_benchmark(store, add_runs, artifacts, compare):
    store({"run-1": {A: 10.0}})
    add_runs(artifacts, {"run-1": {B: 99.0}})
    report = only(compare())
    assert (report.status, report.baseline_only, report.candidate_only) == (
        "compared",
        [A],
        [B],
    )
    assert report.results == []


@pytest.mark.parametrize("side", ["history", "candidate"])
def test_rejects_runners_with_different_benchmarks(
    store, add_runs, artifacts, compare, side
):
    runs = {"run-1": {A: 10.0, B: 10.0}, "run-2": {A: 10.0}}
    complete = {"run-1": {A: 10.0, B: 10.0}}
    store(runs if side == "history" else complete)
    add_runs(artifacts, runs if side == "candidate" else complete)
    with pytest.raises(ArtifactError) as error:
        compare()
    assert str(error.value) == (
        f"{side}: runner execution (test set 'tpch', comparison target 'main',"
        " runner execution 'run-2') lacks benchmarks which other runner executions"
        f" of its test set hold: {B}"
    )


@pytest.mark.parametrize(
    "baseline, candidate, change, regression",
    [
        pytest.param(0.0, 0.0, None, False, id="both-zero"),
        pytest.param(0.0, 1e-3, None, False, id="candidate-at-floor"),
        pytest.param(1e-4, 9e-4, None, False, id="both-below-floor"),
        pytest.param(0.0, 2e-3, None, True, id="zero-baseline"),
        # Compared with the floor: a change of 2% and of exactly the threshold.
        pytest.param(0.99e-3, 1.01e-3, None, False, id="noise-around-floor"),
        pytest.param(0.0, 1.1e-3, None, False, id="floor-plus-threshold"),
        pytest.param(0.0, 1.2e-3, None, True, id="above-floor-plus-threshold"),
        pytest.param(1e-3, 5.0, None, True, id="baseline-at-floor"),
        pytest.param(2e-3, 1e-3, -50.0, False, id="faster-to-floor"),
        pytest.param(2e-3, 3e-3, 50.0, True, id="baseline-above-floor"),
    ],
)
def test_near_zero(
    store, add_runs, artifacts, compare, baseline, candidate, change, regression
):
    store({"run-1": {A: baseline}})
    add_runs(artifacts, {"run-1": {A: candidate}})
    result = only(compare()).results[0]
    if change is None:
        assert result.change_percent is None
    else:
        assert math.isclose(result.change_percent, change)
    assert result.regression is regression


def test_custom_near_zero(store, add_runs, artifacts, compare):
    store({"run-1": {A: 0.001}})
    add_runs(artifacts, {"run-1": {A: 0.002}})
    report = only(compare(near_zero_seconds=0.01))
    assert report.near_zero_seconds == 0.01
    assert report.results[0].change_percent is None
    assert report.regressions == []


def test_floor_respects_threshold(store, add_runs, artifacts, compare):
    store({"run-1": {A: 0.0}})
    add_runs(artifacts, {"run-1": {A: 1.5e-3}})
    assert only(compare(threshold_percent=100.0)).regressions == []


@pytest.mark.parametrize("side", ["baseline", "candidate"])
def test_collection_without_executions_is_missing(add_runs, artifacts, side):
    add_runs(artifacts, {"run-1": {A: 10.0}})
    collection = only_collection(artifacts)
    empty = Collection(test_set_id="tpch", comparison_target="main")
    sides = {"baseline": [empty], "candidate": [collection]}
    if side == "candidate":
        sides = {"baseline": [collection], "candidate": [empty]}
    report = only(compare_collections(sides["baseline"], sides["candidate"]))
    assert report.status == f"missing_{side}"


def test_change_does_not_overflow(add_runs, artifacts, tmp_path):
    add_runs(artifacts, {"run-1": {A: 1e300}})
    candidate = collect_candidates(artifacts)
    add_runs(tmp_path / "baseline", {"run-1": {A: 1e-200}})
    baseline = collect_candidates(tmp_path / "baseline")
    result = only(
        compare_collections(baseline, candidate, near_zero_seconds=1e-300)
    ).results[0]
    assert result.change_percent == sys.float_info.max
    assert result.regression


def _tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_uses_checked_out_history_as_is(
    store, add_runs, artifacts, compare, history_root
):
    # The history was stored at an unrelated revision, not the parent commit.
    store({"run-1": {A: 10.0}}, source_revision="0000000")
    add_runs(artifacts, {"run-1": {A: 12.0}}, source_revision="fffffff")
    before = _tree(history_root)
    assert results(only(compare())) == {A: (20.0, True)}
    assert _tree(history_root) == before


def test_rejects_invalid_statistics(store, add_runs, artifacts, compare):
    store({"run-1": {A: -1.0}})
    add_runs(artifacts, {"run-1": {A: -2.0}, "run-2": {A: 10.0}})
    with pytest.raises(ArtifactError) as error:
        compare()
    lines = str(error.value).splitlines()
    # median, min, max, and mean are invalid in each of the two documents.
    assert [line.split(":")[0] for line in lines] == ["history"] * 4 + ["candidate"] * 4
    assert "'stats.median' -1.0" in lines[0]
    assert "'stats.median' -2.0" in lines[4]
    assert not any("'run-2'" in line for line in lines)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"threshold_percent": -1.0}, "threshold_percent"),
        ({"threshold_percent": math.nan}, "threshold_percent"),
        ({"near_zero_seconds": 0.0}, "near_zero_seconds"),
        ({"near_zero_seconds": math.inf}, "near_zero_seconds"),
    ],
)
def test_rejects_invalid_parameters(kwargs, message):
    with pytest.raises(ValueError, match=message):
        compare_collections([], [], **kwargs)


def test_rejects_test_set_twice_with_the_other_problems(add_runs, artifacts, tmp_path):
    add_runs(artifacts, {"run-1": {A: 10.0}})
    collection = only_collection(artifacts)
    add_runs(tmp_path / "invalid", {"run-1": {A: -1.0}})
    invalid = only_collection(tmp_path / "invalid")
    with pytest.raises(ArtifactError) as error:
        compare_collections([invalid], [collection, collection])
    lines = str(error.value).splitlines()
    assert all(line.startswith("history: ") for line in lines[:-1])
    assert lines[-1] == (
        "candidate: test set 'tpch' of comparison target 'main' occurs twice"
    )


def test_aggregate_collection(add_runs, artifacts):
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
    add_runs, artifacts
):
    add_runs(artifacts, {"run-1": {A: 1.0}, "run-2": {A: 1.0, B: 1.0}})
    collection = only_collection(artifacts)
    with pytest.raises(ArtifactError, match=r"^runner execution .*'run-1'.* hold: "):
        aggregate_collection(collection)


def test_aggregate_collection_rejects_invalid_statistics(add_runs, artifacts):
    add_runs(artifacts, {"run-1": {A: -1.0}})
    collection = only_collection(artifacts)
    with pytest.raises(ArtifactError, match=r"^the benchmark JSON .*'stats.median'"):
        aggregate_collection(collection)
