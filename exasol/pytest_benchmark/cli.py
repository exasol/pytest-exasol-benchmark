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
    _os_message,
    package_artifact,
)
from .cli_output import (
    format_comparison_reports,
    format_store_result,
)
from .comparison import (
    DEFAULT_THRESHOLD_PERCENT,
    compare_with_history,
)
from .history import (
    DEFAULT_HISTORY_ROOT,
    store_history,
)
from .models import (
    IDENTIFIER_RULE,
    ComparisonReport,
    Identifier,
)

_IDENTIFIER = TypeAdapter(Identifier)
_REPORTS = TypeAdapter(list[ComparisonReport])

# The exit status of a comparison which found an excessive difference.
_COMPARISON_FAILURE_EXIT_CODE = 1


class _CommandError(click.ClickException):
    """A command could not be done, for example because of invalid input.

    Every command exits with the same status for it, which differs from that of
    a comparison finding an excessive difference.
    """

    exit_code = 2


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
        raise _CommandError(str(error)) from error
    click.echo(f"Packaged runner artifact to {output_dir}")


def _run_comparison(
    artifacts_dir: Path,
    history_root: Path,
    threshold: float,
    json_output: Path | None,
) -> list[ComparisonReport]:
    """Compare, validate, and optionally serialize runner-artifact reports."""
    if json_output is not None:
        # A failed comparison must not leave the reports of an earlier one.
        try:
            json_output.unlink(missing_ok=True)
        except OSError as error:
            raise _CommandError(
                f"cannot remove earlier reports: {_os_message(error)}"
            ) from error
    try:
        reports = compare_with_history(
            artifacts_dir, history_root, threshold_percent=threshold
        )
    except ArtifactError as error:
        raise _CommandError(str(error)) from error
    except OSError as error:
        # Not every file system error is reported as an ArtifactError, and exit
        # status 1 would report it as a regression.
        raise _CommandError(f"cannot compare: {_os_message(error)}") from error
    if not any(report.status == "compared" for report in reports):
        # Without a compared test set nothing can exceed the tolerance, so passing
        # would hide a mistyped --history-root, test set ID, or comparison
        # target, or a checkout without the history.
        raise _CommandError(
            f"the history in {history_root} holds none of the candidate's test"
            " sets, so nothing can be compared.  Check --history-root and the"
            " test set IDs and comparison targets of the artifacts, or store a"
            " benchmark run as the history first, see the store command"
        )
    if json_output is not None:
        try:
            json_output.write_bytes(_REPORTS.dump_json(reports, indent=2) + b"\n")
        except OSError as error:
            raise _CommandError(
                f"cannot write the reports: {_os_message(error)}"
            ) from error
    return reports


@main.command()
@_artifacts_dir_argument()
@_history_root_option("Checked-out benchmark history used as the baseline.")
@click.option(
    "--threshold",
    default=DEFAULT_THRESHOLD_PERCENT,
    show_default=True,
    type=click.FloatRange(min=0),
    callback=_validate_finite,
    help=(
        "Change in percent: a benchmark slower or faster beyond the tolerance"
        " is a comparison failure."
    ),
)
@click.option(
    "--json-output",
    type=click.Path(dir_okay=False, path_type=Path),
    help=(
        "File the comparison reports are written to as JSON.  An existing file"
        " is removed first, even if the comparison fails."
    ),
)
@click.pass_context
def compare(
    ctx: click.Context,
    artifacts_dir: Path,
    history_root: Path,
    threshold: float,
    json_output: Path | None,
) -> None:
    """Compare runner artifacts with the history.

    Compares the downloaded runner artifacts in ARTIFACTS_DIR with the
    benchmark history of the current checkout and prints a report per test
    set, listing regressions and suspicious speedups separately.  Nothing is
    written to the history.

    Exits with 0 if no benchmark exceeds the tolerance, with 1 if a slowdown
    or speedup does, and with 2, like the other commands, if the comparison
    could not be done, for example because of invalid input or because the
    history holds none of the test sets of the artifacts.
    Test sets and benchmarks held by one side only are reported, but do not
    fail the comparison.
    """
    reports = _run_comparison(artifacts_dir, history_root, threshold, json_output)
    click.echo("\n".join(format_comparison_reports(reports)))
    if any(report.regressions or report.speedups for report in reports):
        ctx.exit(_COMPARISON_FAILURE_EXIT_CODE)


@main.command()
@_artifacts_dir_argument()
@_history_root_option("Benchmark history the collection is written to.")
def store(artifacts_dir: Path, history_root: Path) -> None:
    """Store runner artifacts as the history.

    Stores the runner artifacts in ARTIFACTS_DIR as the benchmark history
    below the history root, replacing the stored runner executions of each
    test set they hold.  Every artifact and test set is validated first: if
    any is invalid or incomplete, nothing is stored.
    """
    try:
        collections = store_history(artifacts_dir, history_root)
    except ArtifactError as error:
        raise _CommandError(str(error)) from error
    except OSError as error:
        # Not every file system error is reported as an ArtifactError.
        raise _CommandError(f"cannot store: {_os_message(error)}") from error
    click.echo("\n".join(format_store_result(collections, history_root)))
