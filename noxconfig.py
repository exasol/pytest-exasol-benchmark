from __future__ import annotations

from pathlib import Path

from exasol.toolbox.config import BaseConfig
from pydantic import computed_field


class Config(BaseConfig):
    @computed_field  # type: ignore[misc]
    @property
    def has_documentation(self) -> bool:
        """
        Indicates that the project serves Sphinx-based documentation. With a few
        exceptions, this should be the case for most projects.
        """
        return False


PROJECT_CONFIG = Config(
    project_name="pytest_benchmark",
    root_path=Path(__file__).parent,
    python_versions=("3.10", "3.11", "3.12", "3.13", "3.14"),
)
