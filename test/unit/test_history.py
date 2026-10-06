import os
import subprocess
import sys
from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest

from exasol.pytest_benchmark.artifact import (
    ArtifactError,
    collect_artifacts,
)
from exasol.pytest_benchmark.history import (
    load_history,
    store_history,
)
from exasol.pytest_benchmark.models import MANIFEST_FILENAME


@pytest.fixture
def history(tmp_path):
    """The root of the benchmark history, not created yet."""
    return tmp_path / "benchmark-history"


def snapshot(root: Path) -> dict[str, bytes | None]:
    """The content of every file and, as None, every directory below *root*."""
    return {
        str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
        for path in sorted(root.rglob("*"))
    }


def identities(root: Path) -> set[tuple[str, str, str]]:
    """The identities of all runner executions in the history below *root*."""
    return {
        execution.manifest.identity
        for collection in load_history(root)
        for execution in collection.executions
    }


def test_collect_returns_bundles_in_directory_order(artifacts, make_bundle):
    make_bundle(artifacts, "run-2")
    make_bundle(artifacts, "run-1")
    assert [b.directory.name for b in collect_artifacts(artifacts)] == [
        "run-1",
        "run-2",
    ]


def test_collect_rejects_empty_directory(artifacts):
    artifacts.mkdir()
    with pytest.raises(ArtifactError, match="contains no runner artifacts"):
        collect_artifacts(artifacts)


def test_collect_rejects_file_entry(artifacts, make_bundle):
    make_bundle(artifacts, "run-1")
    (artifacts / "README").write_text("")
    with pytest.raises(ArtifactError, match="README is not a directory"):
        collect_artifacts(artifacts)


def test_collect_reports_all_problems(artifacts, make_bundle):
    make_bundle(artifacts, "run-1")
    make_bundle(artifacts, "copy", runner_execution_id="run-1")
    (artifacts / "empty").mkdir()
    (make_bundle(artifacts, "broken") / "benchmark.json").unlink()
    with pytest.raises(ArtifactError) as error:
        collect_artifacts(artifacts)
    lines = str(error.value).splitlines()
    assert len(lines) == 3
    assert "broken is missing benchmark.json" in lines[0]
    assert f"empty contains no {MANIFEST_FILENAME}" in lines[1]
    assert "duplicate runner execution" in lines[2]
    assert "'run-1'" in lines[2]
    assert "run-1 and " in lines[2]
    assert lines[2].endswith("copy")


def test_collect_ignores_hidden_entries(artifacts, make_bundle):
    (make_bundle(artifacts, "run-1") / ".DS_Store").write_text("")
    (artifacts / ".DS_Store").write_text("")
    (artifacts / ".cache").mkdir()
    assert [b.directory.name for b in collect_artifacts(artifacts)] == ["run-1"]


def test_collect_rejects_only_hidden_entries(artifacts):
    artifacts.mkdir()
    (artifacts / ".DS_Store").write_text("")
    with pytest.raises(ArtifactError, match="contains no runner artifacts"):
        collect_artifacts(artifacts)


def test_collect_rejects_symlinked_artifact(artifacts, tmp_path, make_bundle):
    make_bundle(artifacts, "run-1")
    target = make_bundle(tmp_path / "elsewhere", "run-2")
    (artifacts / "run-2").symlink_to(target, target_is_directory=True)
    with pytest.raises(ArtifactError) as error:
        collect_artifacts(artifacts)
    assert str(error.value).endswith(
        "run-2 is a symbolic link, not a runner artifact directory"
    )


def test_collect_explains_flat_layout(artifacts, tmp_path, make_bundle):
    # Downloading a single artifact by name puts its files into the directory.
    make_bundle(tmp_path, "artifacts")
    with pytest.raises(ArtifactError) as error:
        collect_artifacts(artifacts)
    lines = str(error.value).splitlines()
    assert len(lines) == 3
    assert "one runner artifact per subdirectory" in lines[0]
    assert "without 'name' and without 'merge-multiple'" in lines[0]
    assert "benchmark.json is not a directory" in lines[1]
    assert f"{MANIFEST_FILENAME} is not a directory" in lines[2]


def test_store_round_trips_test_sets_targets_and_runners(
    artifacts, history, make_bundle
):
    for target in ("main", "saas"):
        for test_set in ("tpch", "tpcds"):
            for runner in ("run-1", "run-2"):
                make_bundle(
                    artifacts,
                    f"{target}-{test_set}-{runner}",
                    test_set_id=test_set,
                    comparison_target=target,
                    runner_execution_id=runner,
                    fullname=f"{target}::{test_set}::{runner}",
                )
    store_history(artifacts, history)
    collections = load_history(history)
    assert len(collections) == 4
    for collection in collections:
        assert [x.manifest.runner_execution_id for x in collection.executions] == [
            "run-1",
            "run-2",
        ]
        for execution in collection.executions:
            fullname = execution.benchmark["benchmarks"][0]["fullname"]
            assert fullname == (
                f"{collection.comparison_target}::{collection.test_set_id}"
                f"::{execution.manifest.runner_execution_id}"
            )


def test_store_copies_bytes_into_layout(artifacts, history, make_bundle):
    source = make_bundle(artifacts, "artifact-1", runner_execution_id="run-1")
    store_history(artifacts, history)
    assert snapshot(history) == {
        "main": None,
        "main/tpch": None,
        "main/tpch/run-1": None,
        **{
            f"main/tpch/run-1/{name}": content
            for name, content in snapshot(source).items()
        },
    }


def test_store_returns_stored_collections(artifacts, history, make_bundle):
    make_bundle(artifacts, "run-1")
    make_bundle(artifacts, "run-2", test_set_id="tpcds")
    collections = store_history(artifacts, history)
    assert sorted(
        (c.test_set_id, [x.manifest.runner_execution_id for x in c.executions])
        for c in collections
    ) == [("tpcds", ["run-2"]), ("tpch", ["run-1"])]


def test_store_replaces_subtree_of_stored_collection(tmp_path, history, make_bundle):
    first = tmp_path / "first"
    make_bundle(first, "run-1")
    make_bundle(first, "run-2")
    store_history(first, history)
    second = tmp_path / "second"
    make_bundle(second, "run-3")
    store_history(second, history)
    assert identities(history) == {("tpch", "main", "run-3")}


def test_store_keeps_other_collections(tmp_path, history, make_bundle):
    first = tmp_path / "first"
    make_bundle(first, "run-1", test_set_id="tpcds")
    make_bundle(first, "run-2", comparison_target="saas")
    make_bundle(first, "run-3")
    store_history(first, history)
    second = tmp_path / "second"
    make_bundle(second, "run-4")
    store_history(second, history)
    assert identities(history) == {
        ("tpcds", "main", "run-1"),
        ("tpch", "saas", "run-2"),
        ("tpch", "main", "run-4"),
    }


def test_store_does_not_copy_hidden_entries(artifacts, history, make_bundle):
    (make_bundle(artifacts, "run-1") / ".DS_Store").write_text("")
    (artifacts / ".DS_Store").write_text("")
    store_history(artifacts, history)
    assert sorted(snapshot(history)) == [
        "main",
        "main/tpch",
        "main/tpch/run-1",
        "main/tpch/run-1/benchmark.json",
        f"main/tpch/run-1/{MANIFEST_FILENAME}",
    ]


def test_store_leaves_no_staging_directory(artifacts, history, make_bundle):
    make_bundle(artifacts, "run-1")
    store_history(artifacts, history)
    store_history(artifacts, history)
    assert [path.name for path in history.iterdir()] == ["main"]


@pytest.mark.parametrize(
    "break_bundle",
    [
        pytest.param(lambda path: (path / MANIFEST_FILENAME).unlink(), id="manifest"),
        pytest.param(lambda path: (path / "benchmark.json").unlink(), id="benchmark"),
        pytest.param(
            lambda path: (path / MANIFEST_FILENAME).write_text("{}"),
            id="invalid-manifest",
        ),
        pytest.param(lambda path: (path / "extra").write_text(""), id="extra-entry"),
    ],
)
def test_store_rejects_incomplete_bundle_leaving_history(
    make_bundle, tmp_path, history, break_bundle
):
    first = tmp_path / "first"
    make_bundle(first, "run-1")
    store_history(first, history)
    before = snapshot(history)
    second = tmp_path / "second"
    make_bundle(second, "run-2")
    break_bundle(make_bundle(second, "run-3"))
    with pytest.raises(ArtifactError, match="run-3"):
        store_history(second, history)
    assert snapshot(history) == before


def test_store_rejects_duplicate_identity(artifacts, history, make_bundle):
    make_bundle(artifacts, "run-1")
    make_bundle(artifacts, "copy", runner_execution_id="run-1")
    with pytest.raises(ArtifactError, match=r"duplicate runner execution .*copy"):
        store_history(artifacts, history)
    assert not history.exists()


def test_store_rejects_empty_artifacts_dir(artifacts, history):
    artifacts.mkdir()
    with pytest.raises(ArtifactError, match="contains no runner artifacts"):
        store_history(artifacts, history)
    assert not history.exists()


def test_store_rejects_manifest_outside_its_subtree(tmp_path, history, make_bundle):
    first = tmp_path / "first"
    make_bundle(first, "run-1")
    store_history(first, history)
    (history / "main" / "tpch").rename(history / "main" / "moved")
    before = snapshot(history)
    second = tmp_path / "second"
    make_bundle(second, "run-2")
    with pytest.raises(ArtifactError, match="moved.*is outside"):
        store_history(second, history)
    assert snapshot(history) == before


def test_store_rejects_other_collection_inside_replaced_subtree(
    tmp_path, history, make_bundle
):
    first = tmp_path / "first"
    make_bundle(first, "run-1")
    store_history(first, history)
    other = tmp_path / "other"
    make_bundle(other, "run-2", test_set_id="tpcds")
    (other / "run-2").rename(history / "main" / "tpch" / "run-2")
    before = snapshot(history)
    second = tmp_path / "second"
    make_bundle(second, "run-3")
    with pytest.raises(ArtifactError, match=r"run-2.*'tpcds'.*is inside.*delete it"):
        store_history(second, history)
    assert snapshot(history) == before


def test_store_rejects_collection_differing_only_in_case(
    make_bundle, tmp_path, history, monkeypatch
):
    first = tmp_path / "first"
    make_bundle(first, "run-1", comparison_target="Main")
    store_history(first, history)
    before = snapshot(history)
    second = tmp_path / "second"
    make_bundle(second, "run-2")
    # Emulates a case-insensitive file system, on which main/tpch is Main/tpch.
    monkeypatch.setattr(
        os.path,
        "samefile",
        lambda first, second: str(first).casefold() == str(second).casefold(),
    )
    with pytest.raises(ArtifactError, match=r"'Main'.*is inside.*would delete it"):
        store_history(second, history)
    monkeypatch.undo()
    assert snapshot(history) == before


def fail_renames(monkeypatch, *, staged: int, restore: bool = False) -> None:
    """Make moving the *staged*-th staged subtree in place fail.

    With *restore*, also make moving a replaced subtree back fail.
    """
    rename = Path.rename
    moved = []

    def failing_rename(self, target):
        """Rename like `Path.rename`, except for the renames meant to fail."""
        if ".store" in self.parts and "new" in self.parts:
            moved.append(self)
            if len(moved) == staged:
                raise OSError(28, "No space left on device", str(target))
        if restore and ".store" in self.parts and "old" in self.parts:
            raise OSError(5, "Input/output error", str(target))
        return rename(self, target)

    monkeypatch.setattr(Path, "rename", failing_rename)


@pytest.fixture
def replaced(tmp_path, history, make_bundle):
    """Store two test sets and return a second store replacing both."""
    first = tmp_path / "first"
    make_bundle(first, "run-1")
    make_bundle(first, "run-2", test_set_id="tpcds")
    store_history(first, history)
    second = tmp_path / "second"
    make_bundle(second, "run-3")
    make_bundle(second, "run-4", test_set_id="tpcds")
    return second


def test_store_restores_history_if_replacing_fails(replaced, history, monkeypatch):
    before = snapshot(history)
    fail_renames(monkeypatch, staged=2)
    with pytest.raises(ArtifactError, match="No space left on device"):
        store_history(replaced, history)
    monkeypatch.undo()
    assert snapshot(history) == before


def test_store_keeps_staging_if_restoring_fails(replaced, history, monkeypatch):
    fail_renames(monkeypatch, staged=2, restore=True)
    with pytest.raises(ArtifactError, match=r"nor restore it.*kept in .*\.store"):
        store_history(replaced, history)
    monkeypatch.undo()
    staging = history / ".store"
    assert (staging / "old" / "main" / "tpcds" / "run-2" / MANIFEST_FILENAME).is_file()


def test_load_ignores_hidden_entries(artifacts, history, make_bundle):
    make_bundle(artifacts, "run-1")
    store_history(artifacts, history)
    (history / "main" / "tpch").rename(history / "main" / ".tpch-old")
    assert load_history(history) == []


def test_load_ignores_hidden_entries_of_execution(artifacts, history, make_bundle):
    make_bundle(artifacts, "run-1")
    store_history(artifacts, history)
    (history / "main" / "tpch" / "run-1" / ".DS_Store").write_text("")
    assert identities(history) == {("tpch", "main", "run-1")}


def test_load_rejects_unexpected_entry_of_execution(artifacts, history, make_bundle):
    make_bundle(artifacts, "run-1")
    store_history(artifacts, history)
    (history / "main" / "tpch" / "run-1" / "extra").write_text("")
    with pytest.raises(ArtifactError, match="unexpected entries: extra"):
        load_history(history)


@pytest.mark.parametrize(
    "break_history",
    [
        pytest.param(
            lambda history: (history / "main" / "tpch" / "run-2").mkdir(),
            id="empty-execution",
        ),
        pytest.param(
            lambda history: (
                history / "main" / "tpch" / "run-1" / MANIFEST_FILENAME
            ).rename(history / "main" / "tpch" / "run-1" / ".manifest.json"),
            id="missing-manifest",
        ),
        pytest.param(
            lambda history: (history / "main" / "tpch" / "notes.txt").write_text(""),
            id="file-in-test-set",
        ),
    ],
)
def test_load_rejects_execution_without_manifest(
    artifacts, history, break_history, make_bundle
):
    make_bundle(artifacts, "run-1")
    store_history(artifacts, history)
    break_history(history)
    with pytest.raises(ArtifactError, match=f"contains no {MANIFEST_FILENAME} file"):
        load_history(history)


def test_load_rejects_symlinked_root(artifacts, history, tmp_path, make_bundle):
    make_bundle(artifacts, "run-1")
    store_history(artifacts, history)
    link = tmp_path / "link"
    link.symlink_to(history, target_is_directory=True)
    with pytest.raises(ArtifactError, match=r"link is a symbolic link"):
        load_history(link)


def test_store_rejects_symlinked_root_leaving_target(tmp_path, history, make_bundle):
    first = tmp_path / "first"
    make_bundle(first, "run-1")
    store_history(first, history)
    before = snapshot(history)
    link = tmp_path / "link"
    link.symlink_to(history, target_is_directory=True)
    second = tmp_path / "second"
    make_bundle(second, "run-2")
    with pytest.raises(ArtifactError, match=r"link is a symbolic link"):
        store_history(second, link)
    assert snapshot(history) == before


@pytest.fixture
def outside(tmp_path, make_bundle):
    """A directory outside the history, holding a valid runner artifact."""
    (tmp_path / "outside").mkdir()
    make_bundle(tmp_path / "outside" / "tpch", "run-9")
    return tmp_path / "outside"


def test_load_rejects_symlinked_directory(artifacts, history, outside, make_bundle):
    make_bundle(artifacts, "run-1")
    store_history(artifacts, history)
    (history / "elsewhere").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArtifactError, match=r"elsewhere is a symbolic link"):
        load_history(history)


def test_load_rejects_symlinked_manifest(artifacts, history, outside, make_bundle):
    make_bundle(artifacts, "run-1")
    store_history(artifacts, history)
    manifest = history / "main" / "tpch" / "run-1" / MANIFEST_FILENAME
    manifest.unlink()
    manifest.symlink_to(outside / "tpch" / "run-9" / MANIFEST_FILENAME)
    with pytest.raises(ArtifactError, match=r"manifest.json is a symbolic link"):
        load_history(history)


def test_store_rejects_symlinked_directory_leaving_history(
    tmp_path, history, outside, make_bundle
):
    first = tmp_path / "first"
    make_bundle(first, "run-1")
    store_history(first, history)
    (history / "main" / "tpcds").symlink_to(outside / "tpch", target_is_directory=True)
    before, before_outside = snapshot(history), snapshot(outside)
    second = tmp_path / "second"
    make_bundle(second, "run-2", test_set_id="tpcds")
    with pytest.raises(ArtifactError, match=r"tpcds is a symbolic link"):
        store_history(second, history)
    assert snapshot(history) == before
    assert snapshot(outside) == before_outside


def test_load_and_store_reject_left_staging_directory(replaced, history):
    (history / ".store" / "old").mkdir(parents=True)
    before = snapshot(history)
    with pytest.raises(ArtifactError, match=r"\.store exists.*interrupted"):
        load_history(history)
    with pytest.raises(ArtifactError, match=r"\.store exists.*interrupted"):
        store_history(replaced, history)
    assert snapshot(history) == before


def test_store_keeps_out_concurrent_load_and_store(replaced, history, monkeypatch):
    """A load or a second store while the first replaces subtrees is rejected."""
    rename = Path.rename
    concurrent: list[Callable[[], object]] = [
        partial(load_history, history),
        partial(store_history, replaced, history),
    ]
    errors = []

    def rename_concurrently(self, target):
        """Rename like `Path.rename`, running the concurrent calls before."""
        while concurrent:
            call = concurrent.pop()
            with pytest.raises(ArtifactError, match=r"\.store exists") as error:
                call()
            errors.append(error)
        return rename(self, target)

    monkeypatch.setattr(Path, "rename", rename_concurrently)
    store_history(replaced, history)
    monkeypatch.undo()
    assert len(errors) == 2
    assert identities(history) == {
        ("tpch", "main", "run-3"),
        ("tpcds", "main", "run-4"),
    }


# Stores the history like store_history, but is killed, without any clean-up,
# when moving the second staged subtree in place.
KILLED_STORE = """
import os, sys
from pathlib import Path
from exasol.pytest_benchmark.history import store_history

rename = Path.rename
moved = []

def killing_rename(self, target):
    if ".store" in self.parts and "new" in self.parts:
        moved.append(self)
        if len(moved) == 2:
            os._exit(9)
    return rename(self, target)

Path.rename = killing_rename
store_history(Path(sys.argv[1]), Path(sys.argv[2]))
"""


def test_load_rejects_history_of_killed_store(replaced, history):
    result = subprocess.run(
        [sys.executable, "-c", KILLED_STORE, str(replaced), str(history)],
        check=False,
    )
    assert result.returncode == 9
    # The history is mixed now: tpch is replaced, tpcds is moved away.
    assert (history / "main" / "tpch" / "run-3").is_dir()
    assert not (history / "main" / "tpcds").exists()
    with pytest.raises(ArtifactError, match=r"\.store exists.*interrupted"):
        load_history(history)
