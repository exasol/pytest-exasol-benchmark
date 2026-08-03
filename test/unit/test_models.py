import json
import math

import pytest
from pydantic import ValidationError

from exasol.pytest_benchmark.history import load_history
from exasol.pytest_benchmark.models import (
    ArtifactManifest,
    ComparisonReport,
    ComparisonResult,
    NormalizedCase,
    PlatformMetadata,
    RunnerExecution,
)
from exasol.pytest_benchmark.models import TestSetCollection as Collection


def make_manifest(**overrides):
    values = {
        "test_set_id": "set",
        "comparison_target": "target",
        "runner_execution_id": "run",
        "source_revision": "revision",
        "platform": {"os": "linux", "architecture": "x86_64"},
    }
    values.update(overrides)
    return ArtifactManifest(**values)


def make_comparison_report(**overrides):
    values = {
        "test_set_id": "set",
        "comparison_target": "target",
        "baseline_execution_id": "baseline",
        "candidate_execution_id": "candidate",
    }
    values.update(overrides)
    return ComparisonReport(**values)


def execution(execution_id="run-1", target="onprem-standard"):
    return RunnerExecution(
        manifest=make_manifest(
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


def test_manifest_rejects_unsupported_schema():
    with pytest.raises(ValidationError):
        make_manifest(schema_version=2)


def test_manifest_rejects_non_json_attributes():
    with pytest.raises(ValidationError):
        make_manifest(attributes={"invalid": object()})


@pytest.mark.parametrize("benchmark_file", ["manifest.json", "MANIFEST.JSON"])
def test_manifest_rejects_benchmark_file_collision(benchmark_file):
    with pytest.raises(ValidationError, match="must not be named manifest.json"):
        make_manifest(benchmark_file=benchmark_file)


def test_manifest_rejects_non_finite_attribute_values():
    with pytest.raises(ValidationError, match="JSON-safe"):
        make_manifest(attributes={"invalid": math.nan})


@pytest.mark.parametrize(
    "benchmark_file",
    ["nested/benchmark.json", r"nested\benchmark.json", "C:benchmark.json"],
)
def test_manifest_rejects_benchmark_file_with_directory(benchmark_file):
    with pytest.raises(ValidationError, match="without directories"):
        make_manifest(benchmark_file=benchmark_file)


@pytest.mark.parametrize("field", ["baseline", "candidate"])
def test_comparison_result_rejects_non_finite_values(field):
    with pytest.raises(ValidationError, match="JSON-safe"):
        ComparisonResult(fullname="test::case", **{field: {"mean": math.nan}})


def test_package_does_not_restrict_wildcard_exports():
    import exasol.pytest_benchmark as benchmark

    assert not hasattr(benchmark, "__all__")


@pytest.mark.parametrize("name", ["linear_row_sql_data_generator", "exasol_benchmark"])
def test_package_exports_existing_public_names(name):
    import exasol.pytest_benchmark as benchmark

    assert hasattr(benchmark, name)


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


def test_normalized_case_accepts_a_fullname():
    assert (
        NormalizedCase(fullname="test::case", data={"mean": 1}).fullname == "test::case"
    )


def test_normalized_case_rejects_an_empty_fullname():
    with pytest.raises(ValidationError):
        NormalizedCase(fullname="", data={})


def test_collection_rejects_duplicate_normalized_case():
    collection = Collection(test_set_id="set", comparison_target="target")
    first_case = NormalizedCase(fullname="test::case", data={"mean": 1})
    collection.add_case(first_case)
    duplicate_case = NormalizedCase(fullname="test::case", data={"mean": 2})
    with pytest.raises(ValueError, match="duplicate"):
        collection.add_case(duplicate_case)


def test_collection_rejects_a_case_key_that_does_not_match_fullname():
    invalid_case = NormalizedCase(fullname="actual-name")
    with pytest.raises(ValidationError, match="case key"):
        Collection(
            test_set_id="set",
            comparison_target="target",
            cases={"wrong-key": invalid_case},
        )


def test_comparison_report_rejects_unsupported_schema_version():
    with pytest.raises(ValidationError, match="unsupported schema version"):
        make_comparison_report(schema_version=2)


def test_comparison_report_accepts_supported_schema_version():
    report = make_comparison_report(schema_version=1)
    assert report.schema_version == 1


def test_runner_execution_rejects_non_object_benchmark_json(tmp_path):
    value = execution()
    (tmp_path / "manifest.json").write_text(value.manifest.to_json(), encoding="utf-8")
    (tmp_path / value.manifest.benchmark_file).write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must contain an object"):
        RunnerExecution.read_from(tmp_path)


def _write_history_artifacts(tmp_path):
    execution("run-1", "target-a").write_to(tmp_path / "target-a" / "set" / "run-1")
    execution("run-2", "target-b").write_to(tmp_path / "target-b" / "set" / "run-2")


def test_history_loads_multiple_targets(tmp_path):
    _write_history_artifacts(tmp_path)
    assert {item.comparison_target for item in load_history(tmp_path)} == {
        "target-a",
        "target-b",
    }


def test_history_preserves_raw_benchmark_data(tmp_path):
    _write_history_artifacts(tmp_path)
    assert (
        json.loads(
            (tmp_path / "target-a" / "set" / "run-1" / "benchmark.json").read_text()
        )
        == execution("run-1", "target-a").benchmark
    )


def test_history_returns_empty_for_missing_directory(tmp_path):
    assert load_history(tmp_path / "missing") == []
