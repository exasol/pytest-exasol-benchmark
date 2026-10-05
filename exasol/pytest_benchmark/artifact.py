"""Packaging of pytest-benchmark JSON as a portable runner artifact.

A runner artifact is a directory holding ``MANIFEST_FILENAME`` and the JSON
written by ``pytest --benchmark-json``.  The JSON is copied byte for byte; it
is parsed only to validate it and to derive the runner platform from its
``machine_info``.
"""

import json
import math
from collections.abc import (
    Iterable,
    Mapping,
)
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import (
    IDENTIFIER_RULE,
    MANIFEST_FILENAME,
    ArtifactManifest,
    BenchmarkDocument,
    PlatformMetadata,
    RunnerExecution,
)

# Maps the PlatformMetadata fields to the machine_info keys they are read from.
_PLATFORM_FIELDS = {
    "os": "system",
    "architecture": "machine",
    "python_version": "python_version",
}

# The pydantic error types an invalid Identifier produces for a string.
_IDENTIFIER_ERRORS = {"string_pattern_mismatch", "string_too_short"}


class ArtifactError(ValueError):
    """A runner artifact or its benchmark JSON is invalid."""


@dataclass(frozen=True)
class ArtifactBundle:
    """A validated runner artifact and the directory it was read from."""

    directory: Path
    execution: RunnerExecution


class _NonFiniteNumber(ValueError):
    """A number in the benchmark JSON is NaN or infinite."""


def _reject_constant(value: str) -> Any:
    raise _NonFiniteNumber(f"contains {value}, which is not a finite number")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise _NonFiniteNumber(f"contains {value}, which is not a finite number")
    return number


def _error_detail(error: Mapping[str, Any]) -> str:
    """Describe one pydantic error in a single line, without its location."""
    if error["type"] == "missing":
        return "is missing"
    if error["type"] in _IDENTIFIER_ERRORS:
        return f"is {error['input']!r}, but {IDENTIFIER_RULE}"
    cause = error.get("ctx", {}).get("error")
    if cause is not None:
        return str(cause)
    return f"is {error['input']!r}: {error['msg']}"


def _describe(error: ValidationError) -> str:
    """Describe all errors of `error` in a single line."""
    problems = []
    for details in error.errors():
        location = ".".join(str(part) for part in details["loc"])
        detail = _error_detail(details)
        problems.append(f"'{location}' {detail}" if location else detail)
    return "; ".join(problems)


def _os_message(error: OSError) -> str:
    """The reason of `error`, naming the file it is about."""
    reason = error.strerror or str(error)
    return f"{reason}: {error.filename}" if error.filename else reason


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise ArtifactError(f"cannot read {path}: {_os_message(error)}") from error


def _parse_benchmark(raw: bytes, source: Path) -> dict[str, Any]:
    """
    Parse and validate the pytest-benchmark JSON `raw` read from `source`.

    Raises an `ArtifactError` naming `source` if `raw` is not a JSON document
    written by ``pytest --benchmark-json``, see `BenchmarkDocument`, or if it
    contains a number which is not finite.
    """
    if not raw.strip():
        raise ArtifactError(f"{source} is empty")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ArtifactError(f"{source} is not UTF-8 encoded: {error}") from error
    try:
        document = json.loads(
            text, parse_constant=_reject_constant, parse_float=_finite_float
        )
    except json.JSONDecodeError as error:
        raise ArtifactError(
            f"{source} is not valid JSON: {error.msg} (line {error.lineno}, "
            f"column {error.colno})"
        ) from error
    except _NonFiniteNumber as error:
        raise ArtifactError(f"{source} {error}") from error
    except RecursionError as error:
        raise ArtifactError(
            f"{source} is not valid JSON: it is nested too deeply"
        ) from error
    except ValueError as error:
        raise ArtifactError(f"{source} is not valid JSON: {error}") from error
    try:
        BenchmarkDocument.model_validate(document)
    except ValidationError as error:
        raise ArtifactError(f"{source} {_describe(error)}") from error
    return document


def _execution(
    manifest: ArtifactManifest, benchmark: dict[str, Any]
) -> RunnerExecution:
    # The benchmark was parsed by _parse_benchmark, so it consists of JSON
    # values with finite numbers only.  Validating it again would walk the
    # whole, possibly large and deeply nested, document once more.
    return RunnerExecution.model_construct(manifest=manifest, benchmark=benchmark)


def _platform(machine_info: dict[str, Any], source: Path) -> PlatformMetadata:
    """
    Derive the runner platform from the `machine_info` of `source`.

    Raises an `ArtifactError` listing every missing or invalid value.
    """
    values = {
        field: machine_info[key]
        for field, key in _PLATFORM_FIELDS.items()
        if machine_info.get(key) is not None
    }
    try:
        return PlatformMetadata.model_validate(values)
    except ValidationError as error:
        problems = [
            f"'machine_info.{_PLATFORM_FIELDS[str(details['loc'][0])]}' "
            f"{_error_detail(details)}"
            for details in error.errors()
        ]
        raise ArtifactError(
            f"{source} has an invalid platform: {'; '.join(problems)}"
        ) from error


def _regular_file(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink()
    except OSError as error:
        raise ArtifactError(f"cannot access {path}: {_os_message(error)}") from error


def validate_artifact(
    directory: Path, *, ignore_hidden: bool = False
) -> RunnerExecution:
    """
    Validate the runner artifact in `directory` and return its execution.

    The directory has to contain exactly ``MANIFEST_FILENAME`` and the benchmark
    file it names, both regular files rather than symbolic links.  With
    `ignore_hidden`, it may contain further entries whose names start with a
    dot.  Raises an `ArtifactError` for any violation.
    """
    manifest_path = directory / MANIFEST_FILENAME
    if not _regular_file(manifest_path):
        raise ArtifactError(f"{directory} contains no {MANIFEST_FILENAME} file")
    try:
        manifest = ArtifactManifest.from_json(
            _read_bytes(manifest_path).decode("utf-8")
        )
    except UnicodeDecodeError as error:
        raise ArtifactError(f"{manifest_path} is not UTF-8 encoded: {error}") from error
    except ValidationError as error:
        raise ArtifactError(
            f"{manifest_path} is invalid: {_describe(error)}"
        ) from error

    expected = {MANIFEST_FILENAME, manifest.benchmark_file}
    try:
        entries = {entry.name for entry in directory.iterdir()}
    except OSError as error:
        raise ArtifactError(f"cannot list {directory}: {_os_message(error)}") from error
    if missing := expected - entries:
        raise ArtifactError(f"{directory} is missing {', '.join(sorted(missing))}")
    if ignore_hidden:
        entries = {name for name in entries if name in expected or name[0] != "."}
    if unexpected := entries - expected:
        raise ArtifactError(
            f"{directory} contains unexpected entries: {', '.join(sorted(unexpected))}"
        )
    benchmark_path = directory / manifest.benchmark_file
    if not _regular_file(benchmark_path):
        raise ArtifactError(f"{benchmark_path} is not a regular file")

    benchmark = _parse_benchmark(_read_bytes(benchmark_path), benchmark_path)
    return _execution(manifest, benchmark)


def describe_identity(manifest: ArtifactManifest) -> str:
    """Name the runner execution identity of `manifest` for error messages."""
    return (
        f"test set {manifest.test_set_id!r}, comparison target"
        f" {manifest.comparison_target!r}, runner execution"
        f" {manifest.runner_execution_id!r}"
    )


def duplicate_identities(sources: Iterable[tuple[Path, ArtifactManifest]]) -> list[str]:
    """
    Describe every runner execution identity occurring more than once.

    `sources` pairs each manifest with the path it was read from.  Each
    description names the identity and the paths of the first and the
    duplicate occurrence.
    """
    first: dict[tuple[str, str, str], Path] = {}
    problems = []
    for path, manifest in sources:
        if (seen := first.setdefault(manifest.identity, path)) != path:
            problems.append(
                f"duplicate runner execution ({describe_identity(manifest)})"
                f" in {path} and {seen}"
            )
    return problems


def problems_error(problems: list[str]) -> ArtifactError:
    """Report all `problems` in one error, one problem per line."""
    return ArtifactError("\n".join(problems))


def _directory(path: Path) -> bool:
    """Whether `path` is a directory rather than a symbolic link to one."""
    try:
        return path.is_dir() and not path.is_symlink()
    except OSError as error:
        raise ArtifactError(f"cannot access {path}: {_os_message(error)}") from error


def collect_artifacts(artifacts_dir: Path) -> list[ArtifactBundle]:
    """
    Validate all runner artifacts in `artifacts_dir` and return them.

    Every entry of `artifacts_dir` has to be a directory holding one runner
    artifact, as validated by `validate_artifact`.  This is the layout of
    artifacts downloaded side by side, for example by GitHub's
    ``actions/download-artifact``.  No two artifacts may share a runner
    execution identity.  The artifacts are returned in directory-name order.

    Every artifact is validated before anything is reported: the `ArtifactError`
    raised lists every invalid artifact and every duplicate identity, one per
    line.  It is also raised if `artifacts_dir` contains no artifact.
    """
    try:
        entries = sorted(artifacts_dir.iterdir())
    except OSError as error:
        raise ArtifactError(
            f"cannot list {artifacts_dir}: {_os_message(error)}"
        ) from error
    if not entries:
        raise ArtifactError(f"{artifacts_dir} contains no runner artifacts")
    problems = []
    bundles = []
    for entry in entries:
        try:
            if not _directory(entry):
                raise ArtifactError(
                    f"{entry} is not a directory holding a runner artifact"
                )
            bundles.append(ArtifactBundle(entry, validate_artifact(entry)))
        except ArtifactError as error:
            problems.append(str(error))
    problems.extend(
        duplicate_identities((b.directory, b.execution.manifest) for b in bundles)
    )
    if problems:
        raise problems_error(problems)
    return bundles


def _write(
    output_dir: Path, exists: bool, manifest: ArtifactManifest, raw: bytes
) -> None:
    """
    Write the artifact to `output_dir`, which `exists` empty or is missing.

    The manifest is written last and atomically, so an interrupted write never
    leaves a manifest without its benchmark file, and history loaders, which
    look for manifests, never pick up an incomplete artifact.  On failure,
    everything this call created, including missing parent directories, is
    removed again.  Nothing written by a concurrent packager is touched: the
    directory and the benchmark file are created exclusively, so a second
    packager fails before it has created anything inside `output_dir`.
    """
    created: list[Path] = []  # innermost last
    try:
        if not exists:
            missing = [p for p in output_dir.parents if not p.exists()]
            output_dir.parent.mkdir(parents=True, exist_ok=True)
            created.extend(reversed(missing))
            output_dir.mkdir()
            created.append(output_dir)
        benchmark_path = output_dir / manifest.benchmark_file
        with benchmark_path.open("xb") as file:
            created.append(benchmark_path)
            file.write(raw)
        manifest.write_to(output_dir)
    except BaseException:
        # Cleaning up must not hide the error which made the write fail.
        for path in reversed(created):
            with suppress(OSError):
                if path.is_dir():
                    path.rmdir()
                else:
                    path.unlink()
        raise


def package_artifact(  # pylint: disable=too-many-arguments
    benchmark_json: Path,
    output_dir: Path,
    *,
    test_set_id: str,
    comparison_target: str,
    runner_execution_id: str,
    source_revision: str,
) -> RunnerExecution:
    """
    Package `benchmark_json` as a runner artifact in `output_dir`.

    `benchmark_json` has to be a file written by ``pytest --benchmark-json``.
    It is copied unchanged, next to a manifest holding the given identifiers and
    the platform from its ``machine_info``.  `output_dir` is created if missing
    and has to be empty otherwise.  Everything is validated before anything is
    written.  A failed write leaves nothing behind, and an interrupted one never
    leaves a manifest.  Raises an `ArtifactError` if the JSON, the identifiers,
    or the output directory are invalid, or if the files cannot be read or
    written.
    """
    raw = _read_bytes(benchmark_json)
    document = _parse_benchmark(raw, benchmark_json)
    try:
        manifest = ArtifactManifest(
            test_set_id=test_set_id,
            comparison_target=comparison_target,
            runner_execution_id=runner_execution_id,
            source_revision=source_revision,
            platform=_platform(document["machine_info"], benchmark_json),
        )
    except ValidationError as error:
        raise ArtifactError(f"invalid artifact metadata: {_describe(error)}") from error

    try:
        exists = output_dir.exists()
        if exists:
            if not output_dir.is_dir():
                raise ArtifactError(f"{output_dir} is not a directory")
            if any(output_dir.iterdir()):
                raise ArtifactError(
                    f"{output_dir} is not empty, refusing to overwrite its contents"
                )
        _write(output_dir, exists, manifest, raw)
    except OSError as error:
        raise ArtifactError(
            f"cannot write the artifact to {output_dir}: {_os_message(error)}"
        ) from error
    return _execution(manifest, document)


__all__ = [
    "ArtifactBundle",
    "ArtifactError",
    "collect_artifacts",
    "package_artifact",
    "validate_artifact",
]
