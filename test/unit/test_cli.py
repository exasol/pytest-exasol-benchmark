import json
from importlib.metadata import entry_points

import pytest
from click.testing import CliRunner

from exasol.pytest_benchmark.cli import main

COMMANDS = ["package", "compare", "store"]


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


def test_compare_accepts_missing_history_root(run, artifacts_dir, tmp_path):
    """A project without stored history yet is a missing baseline, not invalid
    input."""
    result = run(
        "compare", str(artifacts_dir), "--history-root", str(tmp_path / "missing")
    )
    assert result.exit_code == 1
    assert "compare is not implemented yet" in result.output


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
    assert result.exit_code == 1
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
    assert result.exit_code == 1
    assert "Error: cannot write the artifact to" in result.output
    assert "Traceback" not in result.output


def test_package_refuses_non_empty_output_dir(run, package_args, tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "other.txt").write_text("keep")
    result = run("package", *as_args(package_args))
    assert result.exit_code == 1
    assert "refusing to overwrite" in result.output


def test_compare_is_not_implemented(run, artifacts_dir):
    result = run("compare", str(artifacts_dir))
    assert result.exit_code == 1
    assert "compare is not implemented yet" in result.output


def test_store_is_not_implemented(run, artifacts_dir):
    result = run("store", str(artifacts_dir))
    assert result.exit_code == 1
    assert "store is not implemented yet" in result.output


def test_executable_is_registered():
    (script,) = entry_points(group="console_scripts", name="pytest-exasol-benchmark")
    assert script.value == "exasol.pytest_benchmark.cli:main"
