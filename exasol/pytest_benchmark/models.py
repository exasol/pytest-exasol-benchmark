"""Public, versioned models used by benchmark artifacts and comparisons."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION})
Identifier = Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
ModelT = TypeVar("ModelT", bound="Model")


class Model(BaseModel):
    """Base configuration shared by the versioned public models.

    Unknown fields are rejected so accidental schema changes are detected
    early.  The JSON helpers provide one consistent API for public models.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    def to_json(self) -> str:
        """Serialize this model to JSON without losing model fields."""
        return self.model_dump_json()

    @classmethod
    def from_json(cls: type[ModelT], value: str) -> ModelT:
        """Create a model from its JSON representation."""
        return cls.model_validate_json(value)


def _json_safe(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("attributes must contain only JSON-safe values") from error
    return value


class PlatformMetadata(Model):
    """Structured operating-system and architecture information for a runner."""

    os: Identifier
    architecture: Identifier
    python_version: str | None = None


class ArtifactManifest(Model):
    """Metadata for one runner execution stored in ``manifest.json``.

    The test set, comparison target, and runner execution ID form the stable
    execution identity.  ``attributes`` stores project-specific context such
    as database versions and implementation identifiers.
    """

    schema_version: int = SCHEMA_VERSION
    test_set_id: Identifier
    comparison_target: Identifier
    runner_execution_id: Identifier
    source_revision: Identifier
    platform: PlatformMetadata
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    benchmark_file: str = "benchmark.json"

    @field_validator("schema_version")
    @classmethod
    def supported_schema_version(cls, value: int) -> int:
        if value not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported schema version: {value}")
        return value

    _validate_attributes = field_validator("attributes")(_json_safe)

    @field_validator("benchmark_file")
    @classmethod
    def safe_benchmark_file(cls, value: str) -> str:
        if not value or Path(value).name != value or value in {".", ".."}:
            raise ValueError("benchmark_file must be a file name without directories")
        if value.casefold() == "manifest.json":
            raise ValueError("benchmark_file must not be named manifest.json")
        return value


class NormalizedCase(Model):
    """A benchmark case identified by pytest-benchmark's stable ``fullname``.

    Collections use ``fullname`` as the dictionary key, while ``data`` holds
    the normalized, JSON-serializable values used for comparisons.
    """

    fullname: str = Field(min_length=1)
    data: dict[str, JsonValue] = Field(default_factory=dict)

    _validate_data = field_validator("data")(_json_safe)


class RunnerExecution(Model):
    """One artifact manifest and the untouched pytest-benchmark JSON document.

    ``write_to`` stores the manifest and raw benchmark document as separate
    files.  Normalization and comparison are intentionally performed outside
    the raw artifact.
    """

    manifest: ArtifactManifest
    benchmark: dict[str, JsonValue]

    _validate_benchmark = field_validator("benchmark")(_json_safe)

    def write_to(self, directory: Path) -> None:
        """Write this execution to a per-run artifact directory."""
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "manifest.json").write_text(self.manifest.to_json() + "\n", encoding="utf-8")
        (directory / self.manifest.benchmark_file).write_text(
            json.dumps(self.benchmark, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def read_from(cls, directory: Path) -> RunnerExecution:
        """Read an execution from ``manifest.json`` and its benchmark file."""
        manifest = ArtifactManifest.from_json((directory / "manifest.json").read_text(encoding="utf-8"))
        benchmark = json.loads((directory / manifest.benchmark_file).read_text(encoding="utf-8"))
        if not isinstance(benchmark, dict):
            raise ValueError("benchmark JSON must contain an object")
        return cls(manifest=manifest, benchmark=benchmark)


class TestSetCollection(Model):
    """Logical collection for one test set and comparison target.

    Runner execution identities and normalized case fullnames must be unique
    within the collection.
    """

    test_set_id: Identifier
    comparison_target: Identifier
    executions: list[RunnerExecution] = Field(default_factory=list)
    cases: dict[str, NormalizedCase] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_executions(self) -> TestSetCollection:
        identities = [(x.manifest.test_set_id, x.manifest.comparison_target, x.manifest.runner_execution_id) for x in self.executions]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate runner-execution identity")
        for execution in self.executions:
            if (execution.manifest.test_set_id, execution.manifest.comparison_target) != (self.test_set_id, self.comparison_target):
                raise ValueError("execution does not belong to this collection")
        for fullname, case in self.cases.items():
            if fullname != case.fullname:
                raise ValueError("normalized case key must equal fullname")
        return self

    def add(self, execution: RunnerExecution) -> None:
        """Add an execution after validating its identity and collection."""
        self.__class__.model_validate(
            self.model_copy(update={"executions": [*self.executions, execution]})
        )
        self.executions.append(execution)

    def add_case(self, case: NormalizedCase) -> None:
        """Add a normalized case, rejecting a duplicate ``fullname``."""
        if case.fullname in self.cases:
            raise ValueError(f"duplicate normalized case: {case.fullname}")
        self.cases[case.fullname] = case


class ComparisonResult(Model):
    """Comparison of one normalized case between baseline and candidate data."""

    fullname: str = Field(min_length=1)
    baseline: JsonValue = None
    candidate: JsonValue = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    _validate_attributes = field_validator("attributes")(_json_safe)


class ComparisonReport(Model):
    """Serializable comparison report between two runner executions."""

    schema_version: int = SCHEMA_VERSION
    test_set_id: Identifier
    comparison_target: Identifier
    baseline_execution_id: Identifier
    candidate_execution_id: Identifier
    results: list[ComparisonResult] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def supported_schema_version(cls, value: int) -> int:
        if value not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported schema version: {value}")
        return value


__all__ = [
    "ArtifactManifest", "ComparisonReport", "ComparisonResult", "JsonValue",
    "NormalizedCase", "PlatformMetadata", "RunnerExecution", "SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS", "TestSetCollection",
]
