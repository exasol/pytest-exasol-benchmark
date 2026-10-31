import json
from importlib.metadata import entry_points
from pathlib import Path

import pytest
from click.testing import CliRunner

from exasol.pytest_benchmark.cli import main
from exasol.pytest_benchmark.history import (
    load_history,
    store_history,
)
from exasol.pytest_benchmark.models import ComparisonReport

COMMANDS = ["package", "compare", "store"]
A = "test/bench.py::test_a"
B = "test/bench.py::test_b"
C = "test/bench.py::test_c"


@pytest.fixture
def run(tmp_path, monkeypatch):
    """Invokes the CLI in an empty working directory."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    return lambda *args: runner.invoke(main, list(args))


@pytest.fixture
def benchmark_json(tmp_path):
    path = tmp_path / "benchmark.json"
    path.write_text(
        json.dumps(
            {
                "machine_info": {"system": "Linux", "machine": "x86_64"},
                "benchmarks": [{"fullname": "test/bench.py::test_select"}],
            },
            indent=4,
        )
    )
    return path


@pytest.fixture
def artifacts_dir(tmp_path):
    path = tmp_path / "artifacts"
    path.mkdir()
    return path


@pytest.fixture
def history_root(tmp_path):
    """The history of the current checkout, at the default location."""
    return tmp_path / "benchmark-history"


@pytest.fixture
def store(tmp_path, add_runs, history_root):
    """Store the runner executions in *runs* as the history, see `add_runs`."""

    def store_runs(runs, test_set_id="tpch"):
        stored = tmp_path / f"stored-{test_set_id}"
        add_runs(stored, runs, test_set_id)
        store_history(stored, history_root)

    return store_runs


def snapshot(root: Path) -> dict[str, bytes]:
    """The content of every file below *root*, by its relative path."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def package_args(benchmark_json, tmp_path):
    return {
        "--benchmark-json": str(benchmark_json),
        "--test-set-id": "tpch",
        "--comparison-target": "main",
        "--runner-execution-id": "run-1",
        "--source-revision": "01d8074",
        "--output-dir": str(tmp_path / "out"),
    }


def as_args(options: dict[str, str]) -> list[str]:
    return [item for option in options.items() for item in option]


def test_help_lists_all_commands(run):
    result = run("--help")
    assert result.exit_code == 0
    for command in COMMANDS:
        assert command in result.output


@pytest.mark.parametrize("command", COMMANDS)
def test_command_help(run, command):
    result = run(command, "--help")
    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_version(run):
    result = run("--version")
    assert result.exit_code == 0
    assert "version" in result.output


@pytest.mark.parametrize(
    "option",
    [
        "--benchmark-json",
        "--test-set-id",
        "--comparison-target",
        "--runner-execution-id",
        "--source-revision",
        "--output-dir",
    ],
)
def test_package_requires_option(run, package_args, option):
    del package_args[option]
    result = run("package", *as_args(package_args))
    assert result.exit_code == 2
    assert f"Missing option '{option}'" in result.output


@pytest.mark.parametrize("value", ["", "a/b", "-leading-dash", "with space"])
@pytest.mark.parametrize(
    "option",
    [
        "--test-set-id",
        "--comparison-target",
        "--runner-execution-id",
        "--source-revision",
    ],
)
def test_package_rejects_invalid_identifier(run, package_args, option, value):
    package_args[option] = value
    result = run("package", *as_args(package_args))
    assert result.exit_code == 2
    assert f"Invalid value for '{option}'" in result.output
    assert "must start with a letter or digit" in result.output


def test_package_rejects_missing_benchmark_json(run, package_args, tmp_path):
    package_args["--benchmark-json"] = str(tmp_path / "missing.json")
    result = run("package", *as_args(package_args))
    assert result.exit_code == 2
    assert "does not exist" in result.output


@pytest.mark.parametrize("command", ["compare", "store"])
def test_requires_artifacts_dir(run, command):
    result = run(command)
    assert result.exit_code == 2
    assert "Missing argument 'ARTIFACTS_DIR'" in result.output


@pytest.mark.parametrize("command", ["compare", "store"])
def test_rejects_missing_artifacts_dir(run, command, tmp_path):
    result = run(command, str(tmp_path / "missing"))
    assert result.exit_code == 2
    assert "does not exist" in result.output


@pytest.mark.parametrize("create", [False, True], ids=["missing", "empty"])
def test_compare_rejects_history_without_executions(
    run, add_runs, artifacts_dir, tmp_path, create
):
    """Without any baseline nothing can be a regression, so passing would hide a
    mistyped history root."""
    history = tmp_path / "history"
    if create:
        history.mkdir()
    add_runs(artifacts_dir, {"run-1": {A: 1.0}})
    output = tmp_path / "reports.json"
    result = run(
        "compare",
        str(artifacts_dir),
        "--history-root",
        str(history),
        "--json-output",
        str(output),
    )
    assert result.exit_code == 2
    assert (
        f"Error: the history in {history} holds none of the candidate's test sets"
        in result.output
    )
    assert history.exists() is create
    assert not output.exists()


def test_compare_rejects_history_of_other_test_sets_only(
    run, store, make_bundle, artifacts_dir
):
    """A mistyped comparison target compares nothing, even if the history holds
    other test sets."""
    store({"run-1": {A: 1.0}})
    make_bundle(artifacts_dir, "run-1", comparison_target="mian", medians={A: 9.0})
    result = run("compare", str(artifacts_dir))
    assert result.exit_code == 2
    assert "holds none of the candidate's test sets" in result.output


def test_compare_accepts_test_set_missing_in_history(
    run, store, add_runs, artifacts_dir
):
    """A test set new to an existing history is a missing baseline, not invalid
    input."""
    store({"run-1": {A: 1.0}})
    add_runs(artifacts_dir, {"run-1": {A: 1.0}})
    add_runs(artifacts_dir, {"run-1": {A: 9.0}}, test_set_id="fresh")
    result = run("compare", str(artifacts_dir))
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0] == (
        "Test set fresh of comparison target main: not in the history, nothing"
        " compared (1 candidate runner execution)"
    )


@pytest.mark.parametrize("value", ["-1", "nan", "inf", "-inf"])
def test_compare_rejects_invalid_threshold(run, artifacts_dir, value):
    result = run("compare", str(artifacts_dir), "--threshold", value)
    assert result.exit_code == 2
    assert "Invalid value for '--threshold'" in result.output


@pytest.mark.parametrize("command", ["compare", "store"])
def test_rejects_empty_history_root(run, artifacts_dir, command):
    result = run(command, str(artifacts_dir), "--history-root", "")
    assert result.exit_code == 2
    assert "Invalid value for '--history-root': must not be empty" in result.output


def test_package_writes_artifact(run, package_args, benchmark_json, tmp_path):
    result = run("package", *as_args(package_args))
    assert result.exit_code == 0, result.output
    assert f"Packaged runner artifact to {tmp_path / 'out'}" in result.output
    assert (tmp_path / "out" / "manifest.json").is_file()
    assert (tmp_path / "out" / "benchmark.json").read_bytes() == (
        benchmark_json.read_bytes()
    )


def test_package_reports_malformed_json(run, package_args, benchmark_json):
    benchmark_json.write_text('{"benchmarks": [')
    result = run("package", *as_args(package_args))
    assert result.exit_code == 2
    assert "Error:" in result.output
    assert "is not valid JSON" in result.output


def test_package_rejects_empty_output_dir(run, package_args):
    package_args["--output-dir"] = ""
    result = run("package", *as_args(package_args))
    assert result.exit_code == 2
    assert "Invalid value for '--output-dir': must not be empty" in result.output


def test_package_reports_unwritable_output_dir(run, package_args, tmp_path):
    (tmp_path / "file").write_text("")
    package_args["--output-dir"] = str(tmp_path / "file" / "out")
    result = run("package", *as_args(package_args))
    assert result.exit_code == 2
    assert "Error: cannot write the artifact to" in result.output
    assert "Traceback" not in result.output


def test_package_refuses_non_empty_output_dir(run, package_args, tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "other.txt").write_text("keep")
    result = run("package", *as_args(package_args))
    assert result.exit_code == 2
    assert "refusing to overwrite" in result.output


def test_compare_reports_all_outcomes(run, store, add_runs, artifacts_dir):
    """Runner artifacts of several subdirectories are aggregated per test set and
    compared with the history in the current checkout."""
    store(
        {
            "run-1": {A: 1.0, B: 2.0, C: 3.0, "test/bench.py::test_old": 1.0},
            "run-2": {A: 1.0, B: 2.0, C: 3.0, "test/bench.py::test_old": 1.0},
        }
    )
    store({"run-1": {A: 1.0}}, test_set_id="gone")
    add_runs(
        artifacts_dir,
        {
            "run-1": {A: 1.2, B: 1.3, C: 3.1, "test/bench.py::test_new": 1.0},
            "run-2": {A: 1.4, B: 1.0, C: 3.0, "test/bench.py::test_new": 1.0},
            "run-3": {A: 9.0, B: 1.2, C: 2.9, "test/bench.py::test_new": 1.0},
        },
    )
    add_runs(artifacts_dir, {"run-1": {A: 1.0}}, test_set_id="fresh")
    result = run("compare", str(artifacts_dir))
    assert result.exit_code == 1, result.output
    assert result.output.splitlines() == [
        "Test set fresh of comparison target main: not in the history, nothing"
        " compared (1 candidate runner execution)",
        "Test set tpch of comparison target main: compared 2 history runner"
        " executions with 3 of the candidate",
        "  Regressions, slower by more than 10 %:",
        f"      +40.0 %  1 s -> 1.4 s  {A}",
        "  Suspicious speedups, faster by more than 10 %:",
        f"      -40.0 %  2 s -> 1.2 s  {B}",
        "  Within the tolerance:",
        f"       +0.0 %  3 s -> 3 s  {C}",
        "  Only in the candidate:",
        "    test/bench.py::test_new",
        "  Only in the history:",
        "    test/bench.py::test_old",
        "Test set gone of comparison target main: not in the candidate, nothing"
        " compared",
        "Summary: 1 regression, 1 speedup, 1 within the tolerance, 1 benchmark only"
        " in the candidate, 1 benchmark only in the history, 1 test set not in the"
        " history, 1 test set not in the candidate",
    ]


def test_compare_fails_for_suspicious_speedup(run, store, add_runs, artifacts_dir):
    store({"run-1": {A: 1.0, B: 1.0}})
    add_runs(artifacts_dir, {"run-1": {A: 1.05, B: 0.5}})
    result = run("compare", str(artifacts_dir))
    assert result.exit_code == 1, result.output
    assert "Suspicious speedups, faster by more than 10 %:" in result.output
    assert "Regressions" not in result.output
    assert result.output.splitlines()[-1] == (
        "Summary: 0 regressions, 1 speedup, 1 within the tolerance"
    )


@pytest.mark.parametrize(
    "threshold, exit_code, title",
    [
        ("19", 1, "Regressions, slower by more than 19 %:"),
        ("20", 0, "Within the tolerance:"),
        ("2.5", 1, "Regressions, slower by more than 2.5 %:"),
    ],
)
def test_compare_threshold(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    run, store, add_runs, artifacts_dir, threshold, exit_code, title
):
    store({"run-1": {A: 1.0}})
    add_runs(artifacts_dir, {"run-1": {A: 1.2}})
    result = run("compare", str(artifacts_dir), "--threshold", threshold)
    assert result.exit_code == exit_code, result.output
    assert f"  {title}" in result.output.splitlines()


def test_compare_reports_regression_of_zero_baseline(
    run, store, add_runs, artifacts_dir
):
    """A zero baseline has no percentage, even for a regression."""
    store({"run-1": {A: 0.0}})
    add_runs(artifacts_dir, {"run-1": {A: 0.002}})
    result = run("compare", str(artifacts_dir))
    assert result.exit_code == 1, result.output
    assert result.output.splitlines()[1:3] == [
        "  Regressions, slower by more than 10 %:",
        f"          n/a  0 s -> 0.002 s  {A}",
    ]


def test_compare_uses_given_history_root(run, add_runs, artifacts_dir, tmp_path):
    other = tmp_path / "other-history"
    add_runs(tmp_path / "stored", {"run-1": {A: 1.0}})
    store_history(tmp_path / "stored", other)
    add_runs(artifacts_dir, {"run-1": {A: 2.0}})
    result = run("compare", str(artifacts_dir), "--history-root", str(other))
    assert result.exit_code == 1, result.output
    assert f"+100.0 %  1 s -> 2 s  {A}" in result.output


def test_compare_writes_json_output(run, store, add_runs, artifacts_dir, tmp_path):
    store({"run-1": {A: 1.0, B: 1.0}})
    add_runs(artifacts_dir, {"run-1": {A: 2.0, B: 0.5}})
    output = tmp_path / "reports.json"
    result = run("compare", str(artifacts_dir), "--json-output", str(output))
    assert result.exit_code == 1, result.output
    (report,) = (
        ComparisonReport.model_validate(x) for x in json.loads(output.read_text())
    )
    assert report.status == "compared"
    assert [r.fullname for r in report.regressions] == [A]
    assert [r.fullname for r in report.speedups] == [B]


def test_compare_reports_unwritable_json_output(
    run, store, add_runs, artifacts_dir, tmp_path
):
    store({"run-1": {A: 1.0}})
    add_runs(artifacts_dir, {"run-1": {A: 1.0}})
    output = tmp_path / "missing" / "reports.json"
    result = run("compare", str(artifacts_dir), "--json-output", str(output))
    assert result.exit_code == 2
    assert "Error: cannot write the reports: " in result.output
    assert "Traceback" not in result.output


def test_compare_removes_earlier_json_output_on_failure(run, artifacts_dir, tmp_path):
    output = tmp_path / "reports.json"
    output.write_text("[]")
    result = run("compare", str(artifacts_dir), "--json-output", str(output))
    assert result.exit_code == 2
    assert not output.exists()


def test_compare_reports_file_system_error(run, add_runs, artifacts_dir, monkeypatch):
    """A file system error which is no ArtifactError must not exit with the status
    of a regression."""

    def fail(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied", "benchmark-history/.store")

    monkeypatch.setattr(
        "exasol.pytest_benchmark.cli_comparison.compare_with_history", fail
    )
    add_runs(artifacts_dir, {"run-1": {A: 1.0}})
    result = run("compare", str(artifacts_dir))
    assert result.exit_code == 2
    assert (
        "Error: cannot compare: Permission denied: benchmark-history/.store"
        in result.output
    )


def test_compare_does_not_modify_history(
    run, store, add_runs, artifacts_dir, history_root
):
    store({"run-1": {A: 1.0}})
    add_runs(artifacts_dir, {"run-1": {A: 2.0}})
    before = snapshot(history_root)
    result = run("compare", str(artifacts_dir))
    assert result.exit_code == 1, result.output
    assert snapshot(history_root) == before


def test_compare_rejects_empty_artifacts_dir(run, artifacts_dir):
    result = run("compare", str(artifacts_dir))
    assert result.exit_code == 2
    assert "contains no runner artifacts" in result.output


def test_compare_rejects_invalid_artifact(run, store, make_bundle, artifacts_dir):
    store({"run-1": {A: 1.0}})
    (make_bundle(artifacts_dir, "run-1") / "benchmark.json").unlink()
    result = run("compare", str(artifacts_dir))
    assert result.exit_code == 2
    assert "Error: " in result.output
    assert "Traceback" not in result.output


def test_compare_rejects_runners_with_different_benchmarks(
    run, store, add_runs, artifacts_dir
):
    store({"run-1": {A: 1.0, B: 1.0}})
    add_runs(artifacts_dir, {"run-1": {A: 1.0, B: 1.0}, "run-2": {A: 1.0}})
    result = run("compare", str(artifacts_dir))
    assert result.exit_code == 2
    assert (
        "Error: candidate: runner execution (test set 'tpch', comparison target"
        " 'main', runner execution 'run-2') lacks benchmarks"
    ) in result.output


def test_compare_rejects_history_of_interrupted_store(
    run, store, add_runs, artifacts_dir, history_root
):
    store({"run-1": {A: 1.0}})
    (history_root / ".store").mkdir()
    add_runs(artifacts_dir, {"run-1": {A: 1.0}})
    result = run("compare", str(artifacts_dir))
    assert result.exit_code == 2
    assert ".store exists" in result.output
    assert "Traceback" not in result.output


def test_compare_rejects_history_runner_lacking_a_benchmark(
    run, store, add_runs, artifacts_dir, history_root
):
    store({"run-1": {A: 1.0, B: 1.0}})
    # Written past store, which would reject it.
    second = history_root / "main" / "tpch" / "run-2"
    add_runs(history_root.parent / "second", {"run-2": {A: 1.0}})
    (history_root.parent / "second" / "tpch-run-2").rename(second)
    add_runs(artifacts_dir, {"run-1": {A: 1.0, B: 1.0}})
    result = run("compare", str(artifacts_dir))
    assert result.exit_code == 2
    assert "Error: history: runner execution" in result.output


def test_store_writes_history(run, add_runs, artifacts_dir, history_root):
    add_runs(artifacts_dir, {"run-1": {A: 1.0}, "run-2": {A: 2.0}})
    add_runs(artifacts_dir, {"run-1": {A: 1.0}}, test_set_id="tpcds")
    result = run("store", str(artifacts_dir))
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        "Stored 3 runner executions of 2 test sets in benchmark-history",
        "  Test set tpcds of comparison target main: run-1",
        "  Test set tpch of comparison target main: run-1, run-2",
    ]
    collections = load_history(history_root)
    assert [(c.test_set_id, len(c.executions)) for c in collections] == [
        ("tpcds", 1),
        ("tpch", 2),
    ]


def test_store_reports_file_system_error(run, add_runs, artifacts_dir, monkeypatch):
    def fail(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied", "artifacts")

    monkeypatch.setattr("exasol.pytest_benchmark.cli.store_history", fail)
    add_runs(artifacts_dir, {"run-1": {A: 1.0}})
    result = run("store", str(artifacts_dir))
    assert result.exit_code == 2
    assert "Error: cannot store: Permission denied: artifacts" in result.output
    assert "Traceback" not in result.output


def test_store_uses_given_history_root(run, add_runs, artifacts_dir, tmp_path):
    add_runs(artifacts_dir, {"run-1": {A: 1.0}})
    other = tmp_path / "other-history"
    result = run("store", str(artifacts_dir), "--history-root", str(other))
    assert result.exit_code == 0, result.output
    assert f"Stored 1 runner execution of 1 test set in {other}" in result.output
    assert len(load_history(other)) == 1


def test_store_rejects_incomplete_artifact(
    run, store, make_bundle, artifacts_dir, history_root
):
    store({"run-1": {A: 1.0}})
    before = snapshot(history_root)
    make_bundle(artifacts_dir, "run-1")
    (make_bundle(artifacts_dir, "run-2") / "manifest.json").unlink()
    result = run("store", str(artifacts_dir))
    assert result.exit_code == 2
    assert "Error: " in result.output
    assert "run-2" in result.output
    assert snapshot(history_root) == before


def test_store_rejects_runners_with_different_benchmarks(
    run, store, add_runs, artifacts_dir, history_root
):
    store({"run-1": {A: 1.0}})
    before = snapshot(history_root)
    add_runs(artifacts_dir, {"run-1": {A: 1.0, B: 1.0}, "run-2": {A: 1.0}})
    result = run("store", str(artifacts_dir))
    assert result.exit_code == 2
    assert (
        "Error: runner execution (test set 'tpch', comparison target 'main',"
        " runner execution 'run-2') lacks benchmarks"
    ) in result.output
    assert snapshot(history_root) == before


def test_executable_is_registered():
    (script,) = entry_points(group="console_scripts", name="pytest-exasol-benchmark")
    assert script.value == "exasol.pytest_benchmark.cli:main"
