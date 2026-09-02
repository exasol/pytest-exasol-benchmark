"""Loader for the current, Git-trackable benchmark history tree."""

from pathlib import Path

from .models import (
    MANIFEST_FILENAME,
    RunnerExecution,
    TestSetCollection,
)


def _read_executions(root: Path) -> list[RunnerExecution]:
    """Read every execution below *root* in directory-name order.

    Directory names are only a storage convention; identity comes from each
    manifest.  Two manifests sharing the full execution identity describe the
    same runner execution twice and are rejected with both offending manifest
    paths.
    """

    sources: dict[tuple[str, str, str], Path] = {}
    executions: list[RunnerExecution] = []
    for manifest_path in sorted(root.glob(f"**/{MANIFEST_FILENAME}")):
        execution = RunnerExecution.read_from(manifest_path.parent)
        manifest = execution.manifest
        identity = (
            manifest.test_set_id,
            manifest.comparison_target,
            manifest.runner_execution_id,
        )
        if identity in sources:
            raise ValueError(
                f"duplicate runner execution {identity} in {manifest_path} "
                f"and {sources[identity]}"
            )
        sources[identity] = manifest_path
        executions.append(execution)
    return executions


def load_history(root: Path = Path("benchmark-history")) -> list[TestSetCollection]:
    """Load all per-execution artifacts below *root*.

    This deliberately does not look for revision or aggregate-run directories.
    Missing history is represented by an empty list.

    Executions sharing a test set and comparison target are grouped into one
    :class:`TestSetCollection`; that is the expected case.
    """

    if not root.exists():
        return []
    collections: dict[tuple[str, str], TestSetCollection] = {}
    for execution in _read_executions(root):
        key = (execution.manifest.test_set_id, execution.manifest.comparison_target)
        collection = collections.setdefault(
            key,
            TestSetCollection(test_set_id=key[0], comparison_target=key[1]),
        )
        collection.add(execution)
    return list(collections.values())


__all__ = ["load_history"]
