from __future__ import annotations

from pathlib import Path

from exasol.toolbox.config import BaseConfig

PROJECT_CONFIG = BaseConfig(
    project_name="pytest_benchmark",
    root_path=Path(__file__).parent,
)
