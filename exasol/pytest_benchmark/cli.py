"""Command line interface for benchmark artifact tooling.

None of the commands runs pytest or benchmarks.  They process the JSON
created by a direct ``pytest --benchmark-json`` execution and the stored
benchmark history.
"""

import math
from pathlib import Path

import click
from pydantic import (
    TypeAdapter,
    ValidationError,
)

from .artifact import (
    ArtifactError,
    package_artifact,
)
from .history import DEFAULT_HISTORY_ROOT
from .models import (
    IDENTIFIER_RULE,
    Identifier,
)

DEFAULT_THRESHOLD_PERCENT = 10.0

_IDENTIFIER = TypeAdapter(Identifier)


def _validate_identifier(
    _ctx: click.Context, _param: click.Parameter, value: str
) -> str:
    try:
        return _IDENTIFIER.validate_python(value)
    except ValidationError:
        raise click.BadParameter(f"{value!r} {IDENTIFIER_RULE}.") from None


def _identifier_option(name: str, help_text: str):
    return click.option(
        name, required=True, callback=_validate_identifier, help=help_text
    )


def _validate_directory(
    _ctx: click.Context, _param: click.Parameter, value: str
) -> Path:
    # An empty path would silently resolve to the current directory.
    if not value:
        raise click.BadParameter("must not be empty.")
    return Path(value)


def _history_root_option(help_text: str):
    return click.option(
        "--history-root",
        default=str(DEFAULT_HISTORY_ROOT),
        show_default=True,
        type=click.Path(file_okay=False),
        callback=_validate_directory,
        help=help_text,
    )


def _validate_finite(
    _ctx: click.Context, _param: click.Parameter, value: float
) -> float:
    if not math.isfinite(value):
        raise click.BadParameter(f"{value} is not a finite number.")
    return value


def _not_implemented(command: str) -> click.ClickException:
    return click.ClickException(f"{command} is not implemented yet.")


def _artifacts_dir_argument():
    return click.argument(
        "artifacts_dir",
        metavar="ARTIFACTS_DIR",
        type=click.Path(exists=True, file_okay=False, path_type=Path),
    )


@click.group()
@click.version_option(package_name="pytest-exasol-benchmark")
def main() -> None:
    """Package, compare, and store pytest-benchmark results.

    The commands do not run pytest or benchmarks.  Run pytest with
    --benchmark-json directly and process its output with these commands.
    """


@main.command()
@click.option(
    "--benchmark-json",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="JSON file written by pytest --benchmark-json.",
)
@_identifier_option("--test-set-id", "ID of the benchmarked test set.")
@_identifier_option("--comparison-target", "Target the results are compared against.")
@_identifier_option("--runner-execution-id", "ID of this runner execution.")
@_identifier_option("--source-revision", "Revision of the benchmarked source code.")
@click.option(
    "--output-dir",
    required=True,
    type=click.Path(file_okay=False),
    callback=_validate_directory,
    help="Directory the portable runner artifact is written to.",
)
def package(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    benchmark_json: Path,
    test_set_id: str,
    comparison_target: str,
    runner_execution_id: str,
    source_revision: str,
    output_dir: Path,
) -> None:
    """Package benchmark JSON as a runner artifact.

    Packages the JSON written by pytest --benchmark-json as a portable runner
    artifact: the output directory receives the unchanged JSON and a manifest
    with the given IDs and the runner platform.  The output directory has to be
    empty or missing.
    """
    try:
        package_artifact(
            benchmark_json,
            output_dir,
            test_set_id=test_set_id,
            comparison_target=comparison_target,
            runner_execution_id=runner_execution_id,
            source_revision=source_revision,
        )
    except ArtifactError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Packaged runner artifact to {output_dir}")


@main.command()
@_artifacts_dir_argument()
@_history_root_option("Checked-out benchmark history used as the baseline.")
@click.option(
    "--threshold",
    default=DEFAULT_THRESHOLD_PERCENT,
    show_default=True,
    type=click.FloatRange(min=0),
    callback=_validate_finite,
    help="Slowdown in percent above which a benchmark is a regression.",
)
def compare(artifacts_dir: Path, history_root: Path, threshold: float) -> None:
    """Compare runner artifacts with the history.

    Compares the downloaded runner artifacts in ARTIFACTS_DIR with the
    benchmark history of the current checkout.  Exits nonzero only for
    regressions or invalid input.
    """
    raise _not_implemented("compare")


@main.command()
@_artifacts_dir_argument()
@_history_root_option("Benchmark history the collection is written to.")
def store(artifacts_dir: Path, history_root: Path) -> None:
    """Store runner artifacts as the history.

    Stores the runner artifacts in ARTIFACTS_DIR as the benchmark history
    below the history root.
    """
    raise _not_implemented("store")
