import json
import math

import pytest
from pydantic import ValidationError

from exasol.pytest_benchmark.history import load_history
from exasol.pytest_benchmark.models import (
    ArtifactManifest,
    NormalizedCase,
    PlatformMetadata,
    RunnerExecution,
)
from exasol.pytest_benchmark.models import TestSetCollection as Collection


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


def test_manifest_rejects_non_finite_attribute_values():
    with pytest.raises(ValidationError, match="JSON-safe"):
        ArtifactManifest(
            test_set_id="set",
            comparison_target="target",
            runner_execution_id="run",
            source_revision="revision",
            platform={"os": "linux", "architecture": "x86_64"},
            attributes={"invalid": math.nan},
        )


def test_manifest_rejects_benchmark_file_with_directory():
    with pytest.raises(ValidationError, match="without directories"):
        ArtifactManifest(
            test_set_id="set",
            comparison_target="target",
            runner_execution_id="run",
            source_revision="revision",
            platform={"os": "linux", "architecture": "x86_64"},
            benchmark_file="nested/benchmark.json",
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
    duplicate = execution()
    with pytest.raises(ValidationError):
        collection.add(duplicate)


def test_collection_rejects_execution_from_another_collection():
    other_execution = execution(target="other-target")
    with pytest.raises(ValidationError, match="does not belong"):
        Collection(
            test_set_id="tpch-sf10",
            comparison_target="onprem-standard",
            executions=[other_execution],
        )


def test_normalized_case_requires_a_unique_fullname():
    assert (
        NormalizedCase(fullname="test::case", data={"mean": 1}).fullname == "test::case"
    )
    with pytest.raises(ValidationError):
        NormalizedCase(fullname="", data={})
    collection = Collection(test_set_id="set", comparison_target="target")
    first_case = NormalizedCase(fullname="test::case", data={"mean": 1})
    collection.add_case(first_case)
    duplicate_case = NormalizedCase(fullname="test::case", data={"mean": 2})
    with pytest.raises(ValueError, match="duplicate"):
        collection.add_case(duplicate_case)


def test_collection_rejects_a_case_key_that_does_not_match_fullname():
    with pytest.raises(ValidationError, match="case key"):
        Collection(
            test_set_id="set",
            comparison_target="target",
            cases={"wrong-key": NormalizedCase(fullname="actual-name")},
        )


def test_comparison_report_rejects_unsupported_schema_version():
    from exasol.pytest_benchmark.models import ComparisonReport

    report = ComparisonReport(
        schema_version=1,
        test_set_id="set",
        comparison_target="target",
        baseline_execution_id="baseline",
        candidate_execution_id="candidate",
    )
    assert report.schema_version == 1
    with pytest.raises(ValidationError, match="unsupported schema version"):
        ComparisonReport(
            schema_version=2,
            test_set_id="set",
            comparison_target="target",
            baseline_execution_id="baseline",
            candidate_execution_id="candidate",
        )


def test_runner_execution_rejects_non_object_benchmark_json(tmp_path):
    value = execution()
    (tmp_path / "manifest.json").write_text(value.manifest.to_json(), encoding="utf-8")
    (tmp_path / value.manifest.benchmark_file).write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must contain an object"):
        RunnerExecution.read_from(tmp_path)


def test_history_uses_artifact_directories(tmp_path):
    execution("run-1", "target-a").write_to(tmp_path / "target-a" / "set" / "run-1")
    execution("run-2", "target-b").write_to(tmp_path / "target-b" / "set" / "run-2")
    assert {item.comparison_target for item in load_history(tmp_path)} == {
        "target-a",
        "target-b",
    }
    assert (
        json.loads(
            (tmp_path / "target-a" / "set" / "run-1" / "benchmark.json").read_text()
        )
        == execution("run-1", "target-a").benchmark
    )


def test_history_returns_empty_for_missing_directory(tmp_path):
    assert load_history(tmp_path / "missing") == []
