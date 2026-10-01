import json
import os
import stat
from pathlib import Path

import pytest

from exasol.pytest_benchmark import artifact
from exasol.pytest_benchmark.artifact import (
    ArtifactError,
    package_artifact,
    validate_artifact,
)
from exasol.pytest_benchmark.history import load_history
from exasol.pytest_benchmark.models import (
    MANIFEST_FILENAME,
    ArtifactManifest,
)

IDS = {
    "test_set_id": "tpch",
    "comparison_target": "main",
    "runner_execution_id": "run-1",
    "source_revision": "01d8074",
}

# Formatted like pytest-benchmark's output: 4-space indent, ASCII escapes,
# unsorted keys, full float precision, and no trailing newline.
RAW = (
    b"{\n"
    b'    "machine_info": {\n'
    b'        "node": "r\\u00e9ner",\n'
    b'        "system": "Linux",\n'
    b'        "machine": "x86_64",\n'
    b'        "python_version": "3.11.9"\n'
    b"    },\n"
    b'    "commit_info": {},\n'
    b'    "benchmarks": [\n'
    b"        {\n"
    b'            "name": "test_select",\n'
    b'            "fullname": "test/bench.py::test_select",\n'
    b'            "stats": {"mean": 1.0000000000000002e-05, "min": 1e-05}\n'
    b"        }\n"
    b"    ],\n"
    b'    "datetime": "2026-09-29T10:00:00+00:00",\n'
    b'    "version": "5.2.3"\n'
    b"}"
)


def document(**overrides):
    value = json.loads(RAW)
    value.update(overrides)
    return value


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "output.json"
    path.write_bytes(RAW)
    return path


@pytest.fixture
def output_dir(tmp_path):
    return tmp_path / "bundle"


def package(source, output_dir):
    return package_artifact(source, output_dir, **IDS)


def test_package_preserves_raw_bytes(source, output_dir):
    package(source, output_dir)
    assert (output_dir / "benchmark.json").read_bytes() == RAW


def test_package_writes_manifest(source, output_dir):
    package(source, output_dir)
    manifest = ArtifactManifest.from_json(
        (output_dir / MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert manifest.model_dump() == {
        "schema_version": 1,
        **IDS,
        "platform": {
            "os": "Linux",
            "architecture": "x86_64",
            "python_version": "3.11.9",
        },
        "attributes": {},
        "benchmark_file": "benchmark.json",
    }


def test_package_returns_execution(source, output_dir):
    execution = package(source, output_dir)
    assert execution.benchmark == json.loads(RAW)
    assert execution.manifest.runner_execution_id == "run-1"


def test_package_creates_only_manifest_and_benchmark(source, output_dir):
    package(source, output_dir)
    assert sorted(p.name for p in output_dir.iterdir()) == [
        "benchmark.json",
        MANIFEST_FILENAME,
    ]


def test_package_output_is_loadable_as_history(source, tmp_path):
    package(source, tmp_path / "history" / "main" / "tpch" / "run-1")
    (collection,) = load_history(tmp_path / "history")
    assert collection.executions[0].benchmark == json.loads(RAW)


def test_package_accepts_existing_empty_output_dir(source, output_dir):
    output_dir.mkdir()
    package(source, output_dir)
    assert (output_dir / "benchmark.json").read_bytes() == RAW


def test_package_rejects_non_empty_output_dir(source, output_dir):
    output_dir.mkdir()
    (output_dir / "other.txt").write_text("keep")
    with pytest.raises(ArtifactError, match="is not empty, refusing to overwrite"):
        package(source, output_dir)
    assert [p.name for p in output_dir.iterdir()] == ["other.txt"]


def test_package_accepts_missing_python_version(source, output_dir):
    machine_info = document()["machine_info"]
    del machine_info["python_version"]
    source.write_text(json.dumps(document(machine_info=machine_info)))
    execution = package(source, output_dir)
    assert execution.manifest.platform.python_version is None


@pytest.mark.parametrize(
    "raw, message",
    [
        (b"", "is empty"),
        (b"  \n", "is empty"),
        (b'{"benchmarks": "\xff"}', "is not UTF-8 encoded"),
        (b'{\n  "benchmarks": [,]\n}', r"is not valid JSON: .* \(line 2, column 18\)"),
        (b'{"benchmarks": NaN}', "contains NaN, which is not a finite number"),
        (b'{"x": -Infinity}', "contains -Infinity, which is not a finite number"),
        (b"[]", "contains a JSON list instead of the object"),
        (b"{}", "has no 'benchmarks' list"),
        (b'{"benchmarks": {}}', "has no 'benchmarks' list"),
        (b'{"benchmarks": []}', "contains no benchmarks. Was pytest run"),
        (b'{"benchmarks": [1]}', "has no 'fullname' identifying benchmark 0"),
        (
            b'{"benchmarks": [{"fullname": "a"}, {"fullname": ""}]}',
            "has no 'fullname' identifying benchmark 1",
        ),
        (
            b'{"benchmarks": [{"fullname": "a"}, {"fullname": "a"}]}',
            "contains benchmark 'a' twice",
        ),
        (b'{"benchmarks": [{"fullname": "a"}]}', "has no 'machine_info' object"),
        (
            RAW.replace(b"1.0000000000000002e-05", b"1e999"),
            "contains 1e999, which is not a finite number",
        ),
        (b"[" * 100_000 + b"]" * 100_000, "is nested too deeply"),
    ],
    ids=lambda value: value[:40] if isinstance(value, bytes) else None,
)
def test_package_rejects_invalid_json(source, output_dir, raw, message):
    source.write_bytes(raw)
    with pytest.raises(ArtifactError, match=message) as error:
        package(source, output_dir)
    assert str(source) in str(error.value)
    assert sorted(p.name for p in source.parent.iterdir()) == [source.name]


@pytest.mark.parametrize(
    "key, value, message",
    [
        ("system", None, "invalid platform: 'machine_info.system' is missing"),
        ("machine", "", "'machine_info.machine' is '', but must start"),
        ("system", "Linux 6", "'machine_info.system' is 'Linux 6', but must"),
        ("machine", 64, "'machine_info.machine' is 64: Input should be a valid str"),
        ("python_version", 3, "'machine_info.python_version' is 3: Input should"),
    ],
)
def test_package_rejects_invalid_platform(source, output_dir, key, value, message):
    machine_info = document()["machine_info"]
    if value is None:
        del machine_info[key]
    else:
        machine_info[key] = value
    source.write_text(json.dumps(document(machine_info=machine_info)))
    with pytest.raises(ArtifactError, match=message) as error:
        package(source, output_dir)
    assert str(source) in str(error.value)
    assert not output_dir.exists()


def test_package_reports_all_platform_problems(source, output_dir):
    source.write_text(json.dumps(document(machine_info={"machine": ""})))
    with pytest.raises(ArtifactError) as error:
        package(source, output_dir)
    assert "'machine_info.system' is missing; 'machine_info.machine' is ''" in str(
        error.value
    )


def test_package_reports_unreadable_source(tmp_path, output_dir):
    with pytest.raises(ArtifactError, match="cannot read .*missing.json: No such"):
        package(tmp_path / "missing.json", output_dir)


def test_package_rejects_file_as_output_dir(source, tmp_path):
    output = tmp_path / "file"
    output.write_text("keep")
    with pytest.raises(ArtifactError, match="file is not a directory"):
        package(source, output)
    assert output.read_text() == "keep"


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="file permissions do not restrict root",
)
def test_package_reports_unwritable_output_dir(source, tmp_path):
    parent = tmp_path / "readonly"
    parent.mkdir()
    parent.chmod(0o500)
    try:
        with pytest.raises(ArtifactError, match="cannot write the artifact to .*"):
            package(source, parent / "bundle")
    finally:
        parent.chmod(0o700)
    assert list(parent.iterdir()) == []


def test_package_leaves_nothing_behind_when_writing_fails(
    source, output_dir, monkeypatch
):
    def fail(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(ArtifactManifest, "write_to", fail)
    with pytest.raises(ArtifactError, match="No space left on device"):
        package(source, output_dir)
    assert sorted(p.name for p in source.parent.iterdir()) == [source.name]


def test_package_removes_created_parents_when_writing_fails(
    source, tmp_path, monkeypatch
):
    def fail(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(ArtifactManifest, "write_to", fail)
    with pytest.raises(ArtifactError, match="No space left on device"):
        package(source, tmp_path / "a" / "b" / "bundle")
    assert not (tmp_path / "a").exists()


def test_package_keeps_existing_dir_when_writing_fails(source, output_dir, monkeypatch):
    output_dir.mkdir()

    def fail(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(ArtifactManifest, "write_to", fail)
    with pytest.raises(ArtifactError, match="No space left on device"):
        package(source, output_dir)
    assert output_dir.is_dir()
    assert list(output_dir.iterdir()) == []


def test_package_writes_manifest_last(source, output_dir, monkeypatch):
    seen = []
    write_to = ArtifactManifest.write_to

    def record(manifest, directory):
        seen.append(sorted(p.name for p in directory.iterdir()))
        write_to(manifest, directory)

    monkeypatch.setattr(ArtifactManifest, "write_to", record)
    package(source, output_dir)
    assert seen == [["benchmark.json"]]


def test_package_reports_write_error_when_cleanup_fails(
    source, output_dir, monkeypatch
):
    def fail(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    def fail_cleanup(*_args, **_kwargs):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(ArtifactManifest, "write_to", fail)
    monkeypatch.setattr("pathlib.Path.unlink", fail_cleanup)
    with pytest.raises(ArtifactError, match="No space left on device"):
        package(source, output_dir)


def test_package_keeps_files_of_concurrent_packager(source, output_dir):
    """A packager losing the race for a missing output directory fails without
    removing what the winner wrote."""
    output_dir.mkdir()
    (output_dir / "benchmark.json").write_text("winner")
    manifest = package(source, output_dir.parent / "other").manifest
    with pytest.raises(FileExistsError):
        artifact._write(output_dir, False, manifest, RAW)
    with pytest.raises(FileExistsError):
        artifact._write(output_dir, True, manifest, RAW)
    assert (output_dir / "benchmark.json").read_text() == "winner"


def test_manifest_write_leaves_no_partial_manifest(tmp_path, monkeypatch):
    manifest = ArtifactManifest.from_json(
        json.dumps(
            {
                **IDS,
                "platform": {"os": "Linux", "architecture": "x86_64"},
            }
        )
    )

    def fail(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("os.replace", fail)
    with pytest.raises(OSError):
        manifest.write_to(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_manifest_write_uses_unique_temporary_files(tmp_path, monkeypatch):
    manifest = ArtifactManifest.from_json(
        json.dumps({**IDS, "platform": {"os": "Linux", "architecture": "x86_64"}})
    )
    temporaries = []
    replace = os.replace

    def record(source, target):
        temporaries.append(Path(source).name)
        replace(source, target)

    monkeypatch.setattr("os.replace", record)
    manifest.write_to(tmp_path)
    manifest.write_to(tmp_path)
    assert len(set(temporaries)) == 2
    assert not any(name == MANIFEST_FILENAME for name in temporaries)
    assert [p.name for p in tmp_path.iterdir()] == [MANIFEST_FILENAME]


def test_manifest_write_applies_umask(tmp_path):
    manifest = ArtifactManifest.from_json(
        json.dumps({**IDS, "platform": {"os": "Linux", "architecture": "x86_64"}})
    )
    umask = os.umask(0o022)
    try:
        manifest.write_to(tmp_path)
    finally:
        os.umask(umask)
    assert stat.S_IMODE((tmp_path / MANIFEST_FILENAME).stat().st_mode) == 0o644


def test_package_reports_symlink_loop(source, tmp_path):
    (tmp_path / "loop").symlink_to(tmp_path / "loop")
    with pytest.raises(ArtifactError, match="cannot write the artifact to"):
        package(source, tmp_path / "loop" / "bundle")


def test_package_writes_into_current_directory(source, tmp_path, monkeypatch):
    output = tmp_path / "cwd"
    output.mkdir()
    monkeypatch.chdir(output)
    package(source, output / ".")
    # Seen through the working directory, which must not have been replaced.
    assert sorted(os.listdir(".")) == ["benchmark.json", MANIFEST_FILENAME]


def test_package_keeps_existing_output_dir(source, output_dir):
    output_dir.mkdir()
    output_dir.chmod(0o750)
    inode = output_dir.stat().st_ino
    package(source, output_dir)
    assert output_dir.stat().st_ino == inode
    assert stat.S_IMODE(output_dir.stat().st_mode) == 0o750


def test_package_applies_umask_to_new_output_dir(source, output_dir):
    umask = os.umask(0o022)
    try:
        package(source, output_dir)
    finally:
        os.umask(umask)
    assert stat.S_IMODE(output_dir.stat().st_mode) == 0o755


def test_package_accepts_deeply_nested_values(source, output_dir):
    value = document()
    nested: list = []
    for _ in range(500):
        nested = [nested]
    value["benchmarks"][0]["extra_info"] = {"nested": nested}
    source.write_text(json.dumps(value))
    package(source, output_dir)
    assert (output_dir / "benchmark.json").read_bytes() == source.read_bytes()


def test_package_reports_invalid_identifier_in_one_line(source, output_dir):
    with pytest.raises(ArtifactError) as error:
        package_artifact(source, output_dir, **{**IDS, "test_set_id": "a b"})
    assert str(error.value) == (
        "invalid artifact metadata: 'test_set_id' is 'a b', but must start with a"
        " letter or digit and contain only letters, digits, '.', '_' and '-'"
    )


@pytest.fixture
def bundle(source, output_dir):
    package(source, output_dir)
    return output_dir


def test_validate_artifact_accepts_packaged_bundle(bundle):
    assert validate_artifact(bundle).benchmark == json.loads(RAW)


def test_validate_artifact_rejects_missing_manifest(bundle):
    (bundle / MANIFEST_FILENAME).unlink()
    with pytest.raises(ArtifactError, match="contains no manifest.json"):
        validate_artifact(bundle)


def test_validate_artifact_rejects_missing_benchmark(bundle):
    (bundle / "benchmark.json").unlink()
    with pytest.raises(ArtifactError, match="is missing benchmark.json"):
        validate_artifact(bundle)


def test_validate_artifact_rejects_unexpected_entry(bundle):
    (bundle / "extra").mkdir()
    with pytest.raises(ArtifactError, match="contains unexpected entries: extra"):
        validate_artifact(bundle)


def test_validate_artifact_rejects_invalid_manifest(bundle):
    (bundle / MANIFEST_FILENAME).write_text('{"schema_version": 2}')
    with pytest.raises(ArtifactError) as error:
        validate_artifact(bundle)
    assert str(error.value) == (
        f"{bundle / MANIFEST_FILENAME} is invalid: 'schema_version' unsupported"
        " schema version: 2; 'test_set_id' is missing; 'comparison_target' is"
        " missing; 'runner_execution_id' is missing; 'source_revision' is"
        " missing; 'platform' is missing"
    )


def test_validate_artifact_rejects_malformed_manifest(bundle):
    (bundle / MANIFEST_FILENAME).write_text('{"schema_version":')
    with pytest.raises(ArtifactError) as error:
        validate_artifact(bundle)
    assert str(error.value) == (
        f"{bundle / MANIFEST_FILENAME} is invalid: EOF while parsing a value at"
        " line 1 column 18"
    )


def test_validate_artifact_rejects_invalid_benchmark(bundle):
    (bundle / "benchmark.json").write_text("{}")
    with pytest.raises(ArtifactError, match="has no 'benchmarks' list"):
        validate_artifact(bundle)


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="file permissions do not restrict root",
)
def test_validate_artifact_reports_inaccessible_directory(bundle):
    bundle.chmod(0o600)
    try:
        # Python < 3.13 raises for the inaccessible manifest, later versions
        # report it as missing.
        with pytest.raises(ArtifactError, match="cannot access|contains no"):
            validate_artifact(bundle)
    finally:
        bundle.chmod(0o700)


@pytest.mark.parametrize("name", ["benchmark.json", MANIFEST_FILENAME])
def test_validate_artifact_rejects_symlink(bundle, tmp_path, name):
    target = tmp_path / "elsewhere"
    (bundle / name).rename(target)
    (bundle / name).symlink_to(target)
    with pytest.raises(ArtifactError, match="no manifest.json file|not a regular file"):
        validate_artifact(bundle)


def test_package_preserves_real_pytest_benchmark_output(pytester, tmp_path):
    pytester.makepyfile("""
        def test_sum(benchmark):
            benchmark(sum, range(100))
        """)
    raw_json = tmp_path / "output.json"
    result = pytester.runpytest_subprocess(
        "-p", "no:exasol_benchmark", f"--benchmark-json={raw_json}"
    )
    result.assert_outcomes(passed=1)
    execution = package_artifact(raw_json, tmp_path / "bundle", **IDS)
    assert (tmp_path / "bundle" / "benchmark.json").read_bytes() == (
        raw_json.read_bytes()
    )
    assert execution.manifest.platform.architecture
