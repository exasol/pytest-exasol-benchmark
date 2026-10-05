"""Loader and writer of the current, Git-trackable benchmark history tree."""

import os
import shutil
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

# The directory below the history root a store stages its files in.  Creating
# it is exclusive, so it also keeps a second store out, and a store killed
# while replacing subtrees leaves it behind, which makes loading fail.
_STAGING = ".store"


def _walk_error(error: OSError) -> None:
    raise ArtifactError(f"cannot list the history: {_os_message(error)}") from error


def _check_root(root: Path) -> None:
    """Reject a *root* which is a symbolic link, see `_execution_dirs`."""
    if root.is_symlink():
        raise ArtifactError(f"{root} is a symbolic link")


def _execution_dirs(root: Path) -> list[Path]:
    """All execution directories below *root* in path order.

    Every directory below *root* which holds files, or no directories, is an
    execution directory, so one missing its manifest is not overlooked.
    Identifiers never start with a dot, so hidden entries are no part of the
    layout and are skipped.  The history must not contain symbolic links: they
    could make it read or replace files outside *root*.  An `ArtifactError`
    lists all of them.
    """
    directories = []
    symlinks = []
    for directory, dirnames, filenames in os.walk(root, onerror=_walk_error):
        # A directory holding only hidden directories is no leaf either.
        leaf = not dirnames
        # Symbolic links to directories are listed, but not descended into.
        dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        filenames = [name for name in filenames if not name.startswith(".")]
        for name in dirnames + filenames:
            if Path(directory, name).is_symlink():
                symlinks.append(f"{Path(directory, name)} is a symbolic link")
        if MANIFEST_FILENAME in filenames or (
            Path(directory) != root and (filenames or leaf)
        ):
            directories.append(Path(directory))
    if symlinks:
        raise problems_error(sorted(symlinks))
    return sorted(directories)


def _manifest_paths(root: Path) -> list[Path]:
    """The manifests of all execution directories below *root* holding one."""
    return [
        directory / MANIFEST_FILENAME
        for directory in _execution_dirs(root)
        if (directory / MANIFEST_FILENAME).is_file()
    ]


def _read_executions(root: Path) -> list[RunnerExecution]:
    """Read every execution below *root* in directory-name order.

    Each execution directory, see `_execution_dirs`, is validated like a
    packaged artifact, except that hidden entries are ignored, see
    :func:`~exasol.pytest_benchmark.artifact.validate_artifact`.  Directory
    names are only a storage convention; identity comes from each manifest.
    Two manifests sharing the full execution identity describe the same runner
    execution twice and are rejected with both offending manifest paths.
    """

    sources = [
        (
            directory / MANIFEST_FILENAME,
            validate_artifact(directory, ignore_hidden=True),
        )
        for directory in _execution_dirs(root)
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


def _storing_error(root: Path) -> ArtifactError:
    staging = root / _STAGING
    return ArtifactError(
        f"{staging} exists: a store is writing the history in {root}, or one was"
        " interrupted and may have left it partially replaced.  If no store is"
        f" running, restore {root} from Git and remove {staging}"
    )


def _check_not_storing(root: Path) -> None:
    """Reject *root* while a store writes it, or after one was interrupted."""
    staging = root / _STAGING
    if staging.exists() or staging.is_symlink():
        raise _storing_error(root)


def load_history(root: Path = DEFAULT_HISTORY_ROOT) -> list[TestSetCollection]:
    """Load all per-execution artifacts below *root*.

    This deliberately does not look for revision or aggregate-run directories.
    Missing history is represented by an empty list.  Entries whose names start
    with a dot are ignored, except for the staging directory of
    :func:`store_history`: while it exists, a store is running or was
    interrupted, so the history is rejected.  A store which starts and ends
    while the history is read is not detected.

    Executions sharing a test set and comparison target are grouped into one
    :class:`TestSetCollection`; that is the expected case.  Raises an
    :class:`~exasol.pytest_benchmark.artifact.ArtifactError` if an execution is
    invalid or incomplete, if two executions share an identity, or if *root* is
    or contains a symbolic link.
    """

    _check_root(root)
    if not root.exists():
        return []
    _check_not_storing(root)
    try:
        executions = _read_executions(root)
    finally:
        # A store started while reading takes precedence over errors it caused.
        _check_not_storing(root)
    return _collections(executions)


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

    The bundles are staged in `_STAGING` below *root*, which is removed
    afterwards, unless it keeps replaced subtrees which could not be restored.
    Creating it first keeps other stores out while *root* is checked for
    stray manifests, see `_check_no_strays`.  A *root* created by this call is
    removed again if it fails.
    """
    _check_root(root)
    created_root = not root.exists()
    root.mkdir(parents=True, exist_ok=True)
    staging = root / _STAGING
    try:
        try:
            staging.mkdir()
        except FileExistsError as error:
            raise _storing_error(root) from error
        keep = False
        try:
            if not created_root:
                _check_no_strays(root, set(groups))
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


def _groups(
    bundles: Iterable[ArtifactBundle],
) -> dict[_SubtreeKey, list[ArtifactBundle]]:
    """Group *bundles* by the subtree they are stored in, keeping their order."""
    groups: dict[_SubtreeKey, list[ArtifactBundle]] = {}
    for bundle in bundles:
        manifest = bundle.execution.manifest
        groups.setdefault(
            (manifest.comparison_target, manifest.test_set_id), []
        ).append(bundle)
    return groups


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

    Everything is validated before the history is changed.  The collections are
    copied to the staging directory ``<root>/.store`` first and then moved in
    place.  If that fails, the replaced subtrees are restored.  If even that
    fails, the error names the staging directory, which keeps them.

    Only one store may write *root* at a time; the staging directory, created
    before *root* is checked, keeps a second one out.  While it exists,
    :func:`load_history` and further stores reject the history.  A killed store
    leaves it behind, possibly with the history partially replaced; then
    restore *root* from Git and remove the staging directory.

    Returns the stored collections.  Raises an
    :class:`~exasol.pytest_benchmark.artifact.ArtifactError` if an artifact is
    invalid, if two artifacts share an identity, if a store is running or was
    interrupted, if *root* is or contains a symbolic link, if a manifest of a stored
    collection lies outside its subtree in *root*, if a manifest of another
    collection lies inside a replaced subtree, or if the files cannot be read
    or written.
    """
    bundles = collect_artifacts(artifacts_dir)
    groups = _groups(bundles)
    try:
        _write(root, groups)
    except OSError as error:
        raise ArtifactError(
            f"cannot store the history in {root}: {_os_message(error)}"
        ) from error
    return _collections(bundle.execution for bundle in bundles)


__all__ = ["load_history", "store_history"]
