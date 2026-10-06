import json
from collections.abc import Callable
from pathlib import Path

import pytest

from exasol.pytest_benchmark import QueryResult
from exasol.pytest_benchmark.artifact import package_artifact


class RecordingQueryFunc:
    """Stands in for a real ``QueryFunc`` in tests.

    Instead of executing SQL against a database, it records every statement it was
    called with in :attr:`calls`, so tests can assert which statements ran and in
    which order. ``result`` is what the call returns, for tests that need a value
    back.
    """

    def __init__(self, result: QueryResult = None) -> None:
        self.calls: list[str] = []
        self._result = result

    def __call__(self, sql_statement: str) -> QueryResult:
        self.calls.append(sql_statement)
        return self._result


@pytest.fixture
def recording_query_func() -> RecordingQueryFunc:
    return RecordingQueryFunc()


@pytest.fixture
def make_recording_query_func() -> Callable[[QueryResult], RecordingQueryFunc]:
    """Create a ``RecordingQueryFunc`` which returns ``result`` for every call.

    For tests which need a query result back, such as the table size inspector.
    """
    return RecordingQueryFunc


def _benchmark_json(fullname: str = "test/bench.py::test_select") -> bytes:
    """A pytest-benchmark JSON document holding the single benchmark *fullname*."""
    # Indented and unsorted like pytest-benchmark's output, so a re-serialization
    # would show up as a byte difference.
    document = {
        "machine_info": {
            "system": "Linux",
            "machine": "x86_64",
            "python_version": "3.11.9",
        },
        "benchmarks": [
            {"fullname": fullname, "stats": {"mean": 1.0000000000000002e-05}}
        ],
        "version": "5.2.3",
    }
    return json.dumps(document, indent=4).encode()


def _bundle(  # pylint: disable=too-many-arguments
    artifacts: Path,
    name: str,
    *,
    test_set_id: str = "tpch",
    comparison_target: str = "main",
    runner_execution_id: str | None = None,
    source_revision: str = "d66cb7d",
    fullname: str = "test/bench.py::test_select",
) -> Path:
    """Package a runner artifact as the subdirectory *name* of *artifacts*.

    The runner execution ID defaults to *name*.  Returns the artifact directory.
    """
    source = artifacts.parent / f"{name}.json"
    source.write_bytes(_benchmark_json(fullname))
    package_artifact(
        source,
        artifacts / name,
        test_set_id=test_set_id,
        comparison_target=comparison_target,
        runner_execution_id=runner_execution_id or name,
        source_revision=source_revision,
    )
    return artifacts / name


@pytest.fixture
def artifacts(tmp_path) -> Path:
    """The directory runner artifacts are downloaded to, not created yet."""
    return tmp_path / "artifacts"


@pytest.fixture
def make_bundle() -> Callable[..., Path]:
    """Package a runner artifact as a subdirectory of a downloads directory.

    Called with the downloads directory, the subdirectory name, and optionally
    the IDs, the source revision, and the benchmark ``fullname``.
    """
    return _bundle
