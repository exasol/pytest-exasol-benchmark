"""Loader and writer of the current, Git-trackable benchmark history tree."""

import os
import shutil
import uuid
from collections.abc import (
    Callable,
    Iterable,
)
from contextlib import suppress
from functools import partial
from pathlib import Path

from .artifact import (
    ArtifactBundle,
    ArtifactError,
    _os_message,
    collect_artifacts,
    describe_identity,
    duplicate_identities,
    problems_error,
    validate_artifact,
)
from .models import (
    MANIFEST_FILENAME,
    ArtifactManifest,
    RunnerExecution,
    TestSetCollection,
)

DEFAULT_HISTORY_ROOT = Path("benchmark-history")

# A (comparison target, test set ID) pair, naming one subtree of the history.
_SubtreeKey = tuple[str, str]


def _manifest_paths(root: Path) -> list[Path]:
    """All manifests below *root* in path order, skipping hidden entries.

    Identifiers never start with a dot, so hidden entries are no part of the
    layout.  Skipping them keeps a staging directory left behind by an
    interrupted :func:`store_history` out of the history.
    """
    return [
        path
        for path in sorted(root.glob(f"**/{MANIFEST_FILENAME}"))
        if not any(part.startswith(".") for part in path.relative_to(root).parts)
    ]


def _read_executions(root: Path) -> list[RunnerExecution]:
    """Read every execution below *root* in directory-name order.

    Directory names are only a storage convention; identity comes from each
    manifest.  Two manifests sharing the full execution identity describe the
    same runner execution twice and are rejected with both offending manifest
    paths.
    """

    sources = [
        (path, RunnerExecution.read_from(path.parent)) for path in _manifest_paths(root)
    ]
    if problems := duplicate_identities((p, x.manifest) for p, x in sources):
        raise problems_error(problems)
    return [execution for _, execution in sources]


def _collections(executions: Iterable[RunnerExecution]) -> list[TestSetCollection]:
    """Group *executions* into one collection per test set and comparison target.

    The collections and their executions keep the order of *executions*.
    """
    collections: dict[tuple[str, str], TestSetCollection] = {}
    for execution in executions:
        key = (execution.manifest.test_set_id, execution.manifest.comparison_target)
        collection = collections.setdefault(
            key,
            TestSetCollection(test_set_id=key[0], comparison_target=key[1]),
        )
        collection.add(execution)
    return list(collections.values())


def load_history(root: Path = DEFAULT_HISTORY_ROOT) -> list[TestSetCollection]:
    """Load all per-execution artifacts below *root*.

    This deliberately does not look for revision or aggregate-run directories.
    Missing history is represented by an empty list.  Entries whose names start
    with a dot are ignored.

    Executions sharing a test set and comparison target are grouped into one
    :class:`TestSetCollection`; that is the expected case.
    """

    if not root.exists():
        return []
    return _collections(_read_executions(root))


def _subtree(key: _SubtreeKey) -> Path:
    """The path of the subtree of *key*, relative to the history root."""
    return Path(*key)


def _same_directory(first: Path, second: Path) -> bool:
    """Whether both paths name the same existing directory.

    Unlike comparing the paths, this also detects names differing only in case
    on a case-insensitive file system.
    """
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _replaced_by(
    root: Path, manifest_path: Path, keys: set[_SubtreeKey]
) -> _SubtreeKey | None:
    """The key of the stored subtree *manifest_path* lies in, if any."""
    parts = manifest_path.relative_to(root).parts
    if len(parts) < 3:
        return None
    subtree = root / parts[0] / parts[1]
    return next(
        (key for key in keys if _same_directory(subtree, root / _subtree(key))),
        None,
    )


def _check_no_strays(root: Path, keys: set[_SubtreeKey]) -> None:
    """Reject manifests which storing the subtrees of *keys* would mishandle.

    A manifest of a stored collection outside its subtree would be left behind,
    so loading the history would mix it into the stored collection.  A manifest
    of another collection inside a stored subtree would be deleted with it.
    """
    problems = []
    for path in _manifest_paths(root):
        try:
            manifest = ArtifactManifest.from_json(path.read_text(encoding="utf-8"))
        except OSError as error:
            raise ArtifactError(f"cannot read {path}: {_os_message(error)}") from error
        except ValueError as error:
            raise ArtifactError(f"{path} is invalid: {error}") from error
        key = (manifest.comparison_target, manifest.test_set_id)
        replaced_by = _replaced_by(root, path, keys)
        if replaced_by is None and key in keys:
            problems.append(
                f"{path} ({describe_identity(manifest)}) is outside"
                f" {root / _subtree(key)}, so storing the collection would not"
                " replace it"
            )
        elif replaced_by is not None and replaced_by != key:
            problems.append(
                f"{path} ({describe_identity(manifest)}) is inside"
                f" {root / _subtree(replaced_by)}, so storing test set"
                f" {replaced_by[1]!r} of comparison target {replaced_by[0]!r}"
                " would delete it"
            )
    if problems:
        raise problems_error(problems)


def _stage_bundle(bundle: ArtifactBundle, directory: Path) -> None:
    """Copy *bundle* byte for byte into the new *directory* and validate the copy."""
    manifest = bundle.execution.manifest
    try:
        directory.mkdir()
    except FileExistsError as error:
        # Only possible for IDs differing in case on a case-insensitive file system.
        raise ArtifactError(
            f"cannot store {bundle.directory}: {directory.name} collides with"
            " another runner artifact on this file system"
        ) from error
    # The manifest is copied last, like it is written last when packaging.
    for name in (manifest.benchmark_file, MANIFEST_FILENAME):
        shutil.copyfile(bundle.directory / name, directory / name)
    if validate_artifact(directory).manifest != manifest:
        raise ArtifactError(f"{bundle.directory} changed while it was stored")


def _stage(groups: dict[_SubtreeKey, list[ArtifactBundle]], staging: Path) -> None:
    """Copy the bundles of each subtree in *groups* below *staging*.

    *staging* gets the layout of the history, holding only the stored subtrees.
    """
    for key, bundles in groups.items():
        subtree = staging / _subtree(key)
        subtree.parent.mkdir(parents=True, exist_ok=True)
        try:
            subtree.mkdir()
        except FileExistsError as error:
            raise ArtifactError(
                f"cannot store test set {key[1]!r} of comparison target {key[0]!r}:"
                " it collides with another test set on this file system"
            ) from error
        for bundle in bundles:
            _stage_bundle(
                bundle, subtree / bundle.execution.manifest.runner_execution_id
            )


class _RestoreError(ArtifactError):
    """A failed store could not restore the replaced subtrees."""


def _swap(root: Path, keys: Iterable[_SubtreeKey], new: Path, old: Path) -> None:
    """Replace each subtree of *root* by the one staged below *new*.

    Replaced subtrees are moved below *old*.  If a replacement fails, all
    previous ones are undone.  If undoing fails as well, a `_RestoreError`
    naming *old* is raised.
    """
    undo: list[Callable[[], object]] = []
    try:
        for key in keys:
            target = root / _subtree(key)
            if target.exists() or target.is_symlink():
                (old / _subtree(key)).parent.mkdir(parents=True, exist_ok=True)
                target.rename(old / _subtree(key))
                undo.append(partial((old / _subtree(key)).rename, target))
            if not target.parent.exists():
                target.parent.mkdir()
                undo.append(target.parent.rmdir)
            (new / _subtree(key)).rename(target)
            undo.append(partial(target.rename, new / _subtree(key)))
    except BaseException as error:
        # Undoing must not hide the error which made the replacement fail.
        restored = True
        for step in reversed(undo):
            try:
                step()
            except OSError:
                restored = False
        if not restored:
            raise _RestoreError(
                f"cannot store the history in {root}, nor restore it: the"
                f" replaced test sets are kept in {old}"
            ) from error
        raise


def _write(root: Path, groups: dict[_SubtreeKey, list[ArtifactBundle]]) -> None:
    """Replace the subtrees of *groups* in *root* by their bundles.

    The bundles are staged in a hidden directory below *root*, which is removed
    afterwards, unless it keeps replaced subtrees which could not be restored.
    A *root* created by this call is removed again if it fails.
    """
    created_root = not root.exists()
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".store-{uuid.uuid4().hex}"
    try:
        staging.mkdir()
        keep = False
        try:
            _stage(groups, staging / "new")
            _swap(root, groups, staging / "new", staging / "old")
        except _RestoreError:
            # The staging directory holds the only copy of the replaced history.
            keep = True
            raise
        finally:
            if not keep:
                shutil.rmtree(staging, ignore_errors=True)
    except BaseException:
        if created_root:
            with suppress(OSError):
                root.rmdir()
        raise


def store_history(
    artifacts_dir: Path, root: Path = DEFAULT_HISTORY_ROOT
) -> list[TestSetCollection]:
    """Store the runner artifacts in *artifacts_dir* as the history below *root*.

    *artifacts_dir* holds one runner artifact per subdirectory, see
    :func:`~exasol.pytest_benchmark.artifact.collect_artifacts`.  Each artifact
    is copied byte for byte to
    ``<root>/<comparison-target>/<test-set-id>/<runner-execution-id>/``.

    Storing replaces the whole ``<comparison-target>/<test-set-id>`` subtree of
    each collection in *artifacts_dir*, so runner executions of an earlier
    store do not remain in the baseline.  Earlier baselines are recovered from
    Git.  Subtrees of other collections are left untouched.

    Everything is validated before anything is changed.  The collections are
    copied to a hidden staging directory below *root* first and then moved in
    place.  If that fails, the replaced subtrees are restored.  If even that
    fails, the error names the staging directory, which keeps them.  An
    interrupted store may leave the staging directory behind;
    :func:`load_history` ignores it.

    Returns the stored collections.  Raises an
    :class:`~exasol.pytest_benchmark.artifact.ArtifactError` if an artifact is
    invalid, if two artifacts share an identity, if a manifest of a stored
    collection lies outside its subtree in *root*, if a manifest of another
    collection lies inside a replaced subtree, or if the files cannot be read
    or written.
    """
    bundles = collect_artifacts(artifacts_dir)
    groups: dict[_SubtreeKey, list[ArtifactBundle]] = {}
    for bundle in bundles:
        manifest = bundle.execution.manifest
        key = (manifest.comparison_target, manifest.test_set_id)
        groups.setdefault(key, []).append(bundle)
    try:
        if root.exists():
            _check_no_strays(root, set(groups))
        _write(root, groups)
    except OSError as error:
        raise ArtifactError(
            f"cannot store the history in {root}: {_os_message(error)}"
        ) from error
    return _collections(bundle.execution for bundle in bundles)


__all__ = ["load_history", "store_history"]
