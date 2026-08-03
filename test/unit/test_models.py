import json

import pytest
from pydantic import ValidationError

from exasol.pytest_benchmark.history import load_history
from exasol.pytest_benchmark.models import (
    ArtifactManifest,
    NormalizedCase,
    PlatformMetadata,
    RunnerExecution,
    TestSetCollection as Collection,
)


def execution(execution_id="run-1", target="onprem-standard"):
    return RunnerExecution(
        manifest=ArtifactManifest(
            test_set_id="tpch-sf10",
            comparison_target=target,
            runner_execution_id=execution_id,
            source_revision="8f12ab4",
            platform=PlatformMetadata(os="ubuntu-24.04", architecture="x86_64"),
            attributes={"database": {"version": "8.31.0"}},
        ),
        benchmark={"benchmarks": [{"fullname": "test::case", "stats": {"mean": 1.2}}]},
    )


def test_runner_execution_json_round_trip():
    value = execution()
    assert RunnerExecution.from_json(value.to_json()) == value


def test_manifest_rejects_unsupported_schema_and_non_json_attributes():
    with pytest.raises(ValidationError):
        ArtifactManifest(
            schema_version=2,
            test_set_id="set",
            comparison_target="target",
            runner_execution_id="run",
            source_revision="revision",
            platform={"os": "linux", "architecture": "x86_64"},
        )
    with pytest.raises(ValidationError):
        ArtifactManifest(
            test_set_id="set",
            comparison_target="target",
            runner_execution_id="run",
            source_revision="revision",
            platform={"os": "linux", "architecture": "x86_64"},
            attributes={"invalid": object()},
        )


@pytest.mark.parametrize("benchmark_file", ["manifest.json", "MANIFEST.JSON"])
def test_manifest_rejects_benchmark_file_collision(benchmark_file):
    with pytest.raises(ValidationError, match="must not be named manifest.json"):
        ArtifactManifest(
            test_set_id="set",
            comparison_target="target",
            runner_execution_id="run",
            source_revision="revision",
            platform={"os": "linux", "architecture": "x86_64"},
            benchmark_file=benchmark_file,
        )


def test_existing_package_public_names_are_not_restricted():
    import exasol.pytest_benchmark as benchmark

    assert not hasattr(benchmark, "__all__")
    assert hasattr(benchmark, "linear_row_sql_data_generator")
    assert hasattr(benchmark, "exasol_benchmark")


def test_collection_rejects_duplicate_runner_identity():
    collection = Collection(
        test_set_id="tpch-sf10",
        comparison_target="onprem-standard",
        executions=[execution()],
    )
    with pytest.raises(ValidationError):
        collection.add(execution())


def test_normalized_case_requires_a_unique_fullname():
    assert NormalizedCase(fullname="test::case", data={"mean": 1}).fullname == "test::case"
    with pytest.raises(ValidationError):
        NormalizedCase(fullname="", data={})
    collection = Collection(test_set_id="set", comparison_target="target")
    collection.add_case(NormalizedCase(fullname="test::case", data={"mean": 1}))
    with pytest.raises(ValueError, match="duplicate"):
        collection.add_case(NormalizedCase(fullname="test::case", data={"mean": 2}))


def test_history_uses_artifact_directories(tmp_path):
    execution("run-1", "target-a").write_to(tmp_path / "target-a" / "set" / "run-1")
    execution("run-2", "target-b").write_to(tmp_path / "target-b" / "set" / "run-2")
    assert {item.comparison_target for item in load_history(tmp_path)} == {"target-a", "target-b"}
    assert json.loads((tmp_path / "target-a" / "set" / "run-1" / "benchmark.json").read_text()) == execution("run-1", "target-a").benchmark
