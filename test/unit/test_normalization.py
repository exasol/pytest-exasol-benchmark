import copy
import json
from pathlib import Path

import pytest

from exasol.pytest_benchmark.artifact import (
    ArtifactError,
    package_artifact,
)
from exasol.pytest_benchmark.normalization import (
    RETAINED_STATISTICS,
    normalize_benchmark,
    normalize_execution,
)

# Written by pytest-benchmark 5.3.0 for test/test_bench.py, whose source is
#
#     @pytest.mark.parametrize("size", [10, 100])
#     def test_sum(benchmark, size):
#         benchmark(sum, range(size))
#
#     def test_sorted(benchmark):
#         benchmark.extra_info["rows"] = 50
#         benchmark.pedantic(
#             sorted, args=(list(range(50, 0, -1)),), rounds=5, iterations=2
#         )
#
# run with "pytest -p no:exasol_benchmark test --benchmark-json=benchmark.json
# --benchmark-max-time=0.00001 --benchmark-min-rounds=5".  Only
# machine_info.node was anonymized, and a final newline was added.
FIXTURE = Path(__file__).parent / "resources" / "benchmark.json"
SOURCE = "output.json"
MISSING = object()
FULLNAMES = [
    "test/test_bench.py::test_sum[10]",
    "test/test_bench.py::test_sum[100]",
    "test/test_bench.py::test_sorted",
]


@pytest.fixture
def document():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def execution(tmp_path):
    return package_artifact(
        FIXTURE,
        tmp_path / "artifact",
        test_set_id="tpch",
        comparison_target="main",
        runner_execution_id="run-1",
        source_revision="09983d5",
    )


def stats(document, index=0):
    return document["benchmarks"][index]["stats"]


def test_fixture_is_representative(document):
    assert [b["fullname"] for b in document["benchmarks"]] == FULLNAMES
    assert all(stats(document, i)["data"] for i in range(len(FULLNAMES)))
    assert document["benchmarks"][2]["extra_info"] == {"rows": 50}


def test_normalize_keys_cases_by_fullname_in_document_order(document):
    cases = normalize_benchmark(document, SOURCE)
    assert list(cases) == FULLNAMES
    assert all(fullname == case.fullname for fullname, case in cases.items())


def test_normalize_retains_only_the_retained_statistics(document):
    cases = normalize_benchmark(document, SOURCE)
    for index, fullname in enumerate(FULLNAMES):
        expected = {name: stats(document, index)[name] for name in RETAINED_STATISTICS}
        assert cases[fullname].data == expected


def test_normalize_retains_median_min_max_mean_and_rounds():
    assert set(RETAINED_STATISTICS) == {"median", "min", "max", "mean", "rounds"}


def test_normalize_accepts_integer_timings(document):
    stats(document).update(min=0, median=1, mean=1, max=2)
    case = normalize_benchmark(document, SOURCE)[FULLNAMES[0]]
    assert case.data == {
        "median": 1,
        "min": 0,
        "max": 2,
        "mean": 1,
        "rounds": stats(document)["rounds"],
    }


def test_normalize_does_not_change_the_document(document):
    original = copy.deepcopy(document)
    normalize_benchmark(document, SOURCE)
    assert document == original


def test_normalize_execution(execution):
    assert list(normalize_execution(execution)) == FULLNAMES


def test_normalize_execution_names_the_runner_execution(execution):
    del stats(execution.benchmark)["median"]
    with pytest.raises(ArtifactError) as error:
        normalize_execution(execution)
    assert str(error.value) == (
        "the benchmark JSON of runner execution (test set 'tpch', comparison target"
        " 'main', runner execution 'run-1') has no 'stats.median' for benchmark"
        f" {FULLNAMES[0]!r}"
    )


def remove_benchmarks(document):
    document["benchmarks"] = []


def remove_benchmark_list(document):
    del document["benchmarks"]


def duplicate_fullname(document):
    document["benchmarks"][1]["fullname"] = FULLNAMES[0]


def remove_fullname(document):
    del document["benchmarks"][1]["fullname"]


def remove_machine_info(document):
    del document["machine_info"]


@pytest.mark.parametrize(
    "change, message",
    [
        (remove_benchmarks, "output.json contains no benchmarks. "),
        (remove_benchmark_list, "output.json has no 'benchmarks' list. "),
        (
            duplicate_fullname,
            f"output.json contains benchmark {FULLNAMES[0]!r} twice",
        ),
        (remove_fullname, "output.json has no 'fullname' identifying benchmark 1"),
        (remove_machine_info, "output.json has no 'machine_info' object"),
    ],
)
def test_normalize_rejects_invalid_structure(document, change, message):
    change(document)
    with pytest.raises(ArtifactError) as error:
        normalize_benchmark(document, SOURCE)
    assert str(error.value).startswith(message)


def test_normalize_rejects_a_document_which_is_no_object():
    with pytest.raises(ArtifactError, match=r"^output.json contains a JSON list "):
        normalize_benchmark([], SOURCE)  # type: ignore[arg-type]


@pytest.mark.parametrize("name", RETAINED_STATISTICS)
def test_normalize_rejects_missing_statistic(document, name):
    del stats(document)[name]
    with pytest.raises(ArtifactError) as error:
        normalize_benchmark(document, SOURCE)
    assert str(error.value) == (
        f"output.json has no 'stats.{name}' for benchmark {FULLNAMES[0]!r}"
    )


@pytest.mark.parametrize("value", [MISSING, None, [], "stats"])
def test_normalize_rejects_stats_which_are_no_object(document, value):
    if value is MISSING:
        del document["benchmarks"][0]["stats"]
    else:
        document["benchmarks"][0]["stats"] = value
    with pytest.raises(ArtifactError) as error:
        normalize_benchmark(document, SOURCE)
    assert str(error.value) == (
        f"output.json has no 'stats' object for benchmark {FULLNAMES[0]!r}"
    )


@pytest.mark.parametrize(
    "name, value",
    [
        ("median", "x"),
        ("median", None),
        ("median", True),
        ("median", -1e-06),
        ("median", float("nan")),
        ("median", float("inf")),
        ("min", [1.0]),
        ("max", False),
        ("mean", -1),
        ("mean", 10**400),
    ],
)
def test_normalize_rejects_invalid_timing(document, name, value):
    stats(document)[name] = value
    with pytest.raises(ArtifactError) as error:
        normalize_benchmark(document, SOURCE)
    assert str(error.value) == (
        f"output.json has 'stats.{name}' {value!r} for benchmark"
        f" {FULLNAMES[0]!r}, which is not a finite non-negative number"
    )


@pytest.mark.parametrize("value", [0, -5, 1.5, 5.0, "5", True, None])
def test_normalize_rejects_invalid_rounds(document, value):
    stats(document)["rounds"] = value
    with pytest.raises(ArtifactError) as error:
        normalize_benchmark(document, SOURCE)
    assert str(error.value) == (
        f"output.json has 'stats.rounds' {value!r} for benchmark"
        f" {FULLNAMES[0]!r}, which is not a positive whole number"
    )


def set_timings(document, **timings):
    stats(document).update(timings)


@pytest.mark.parametrize(
    "timings",
    [
        {"min": 2.0, "median": 1.0, "mean": 2.0, "max": 3.0},
        {"min": 1.0, "median": 4.0, "mean": 2.0, "max": 3.0},
        {"min": 1.0, "median": 2.0, "mean": 0.5, "max": 3.0},
        {"min": 1.0, "median": 2.0, "mean": 3.5, "max": 3.0},
        {"min": 4.0, "median": 2.0, "mean": 2.0, "max": 1.0},
    ],
)
def test_normalize_rejects_inconsistent_timings(document, timings):
    set_timings(document, **timings)
    with pytest.raises(ArtifactError) as error:
        normalize_benchmark(document, SOURCE)
    assert str(error.value) == (
        f"output.json has 'stats.min' {timings['min']!r}, 'stats.median'"
        f" {timings['median']!r}, 'stats.mean' {timings['mean']!r}, 'stats.max'"
        f" {timings['max']!r}, but the median and the mean have to lie between"
        f" the minimum and the maximum for benchmark {FULLNAMES[0]!r}"
    )


def test_normalize_accepts_equal_timings(document):
    set_timings(document, min=1.0, median=1.0, mean=1.0, max=1.0)
    case = normalize_benchmark(document, SOURCE)[FULLNAMES[0]]
    assert case.data == {
        "median": 1.0,
        "min": 1.0,
        "max": 1.0,
        "mean": 1.0,
        "rounds": stats(document)["rounds"],
    }


def test_normalize_checks_consistency_only_of_valid_timings(document):
    set_timings(document, min="x", median=5.0)
    with pytest.raises(ArtifactError) as error:
        normalize_benchmark(document, SOURCE)
    assert str(error.value) == (
        f"output.json has 'stats.min' 'x' for benchmark {FULLNAMES[0]!r},"
        " which is not a finite non-negative number"
    )


def test_normalize_reports_structure_errors_before_statistics(document):
    del stats(document, 0)["median"]
    duplicate_fullname(document)
    with pytest.raises(ArtifactError) as error:
        normalize_benchmark(document, SOURCE)
    assert str(error.value) == (
        f"output.json contains benchmark {FULLNAMES[0]!r} twice"
    )


def test_normalize_reports_all_problems_at_once(document):
    del stats(document, 0)["median"]
    stats(document, 0)["rounds"] = 0
    del document["benchmarks"][2]["stats"]
    with pytest.raises(ArtifactError) as error:
        normalize_benchmark(document, SOURCE)
    assert str(error.value).splitlines() == [
        f"output.json has no 'stats.median' for benchmark {FULLNAMES[0]!r}",
        f"output.json has 'stats.rounds' 0 for benchmark {FULLNAMES[0]!r},"
        " which is not a positive whole number",
        f"output.json has no 'stats' object for benchmark {FULLNAMES[2]!r}",
    ]


def test_normalize_names_a_path_source(document, tmp_path):
    del stats(document)["mean"]
    with pytest.raises(ArtifactError, match=r"output\.json has no 'stats\.mean'"):
        normalize_benchmark(document, tmp_path / "output.json")
