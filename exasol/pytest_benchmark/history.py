"""Loader for the current, Git-trackable benchmark history tree."""

from pathlib import Path

from .models import (
    RunnerExecution,
    TestSetCollection,
)


def load_history(root: Path = Path("benchmark-history")) -> list[TestSetCollection]:
    """Load all per-execution artifacts below *root*.

    Directory names are only a storage convention; identity comes from each
    manifest.  This deliberately does not look for revision or aggregate-run
    directories.  Missing history is represented by an empty list.
    """

    collections: dict[tuple[str, str], TestSetCollection] = {}
    if not root.exists():
        return []
    for manifest_path in sorted(root.glob("**/manifest.json")):
        execution = RunnerExecution.read_from(manifest_path.parent)
        key = (execution.manifest.test_set_id, execution.manifest.comparison_target)
        collection = collections.setdefault(
            key,
            TestSetCollection(test_set_id=key[0], comparison_target=key[1]),
        )
        collection.add(execution)
    return list(collections.values())


__all__ = ["load_history"]
