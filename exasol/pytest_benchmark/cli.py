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
    ComparisonResult,
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


def _plural(count: int, noun: str) -> str:
    """`count` followed by `noun`, with an ``s`` appended unless `count` is 1."""
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _seconds(value: float) -> str:
    """A timing in seconds, rounded to four significant digits."""
    return f"{value:.4g} s"


def _format_result(result: ComparisonResult) -> str:
    """
    One indented line of a report: the change in percent, right-aligned, the
    baseline and candidate timings, and the benchmark's fullname.
    """
    change = result.change_percent
    # No percentage for a zero baseline or a non-finite calculation.
    text = "n/a" if change is None else f"{change:+.1f} %"
    return (
        f"    {text:>9}  {_seconds(result.baseline)} ->"
        f" {_seconds(result.candidate)}  {result.fullname}"
    )


def _format_report(report: ComparisonReport) -> list[str]:
    """
    The lines describing `report`.

    A test set held by one side only is described by a single line.  For a
    compared one, a header is followed by sections for the regressions, the
    speedups, the results within the tolerance, and the benchmarks held by one
    side only; empty sections are left out.
    """
    name = (
        f"Test set {report.test_set_id} of comparison target"
        f" {report.comparison_target}"
    )
    baseline_ids = report.baseline_execution_ids
    candidate_ids = report.candidate_execution_ids
    if report.status == "missing_baseline":
        return [
            f"{name}: not in the history, nothing compared"
            f" ({_plural(len(candidate_ids), 'candidate runner execution')})"
        ]
    if report.status == "missing_candidate":
        return [f"{name}: not in the candidate, nothing compared"]
    lines = [
        f"{name}: compared"
        f" {_plural(len(baseline_ids), 'history runner execution')}"
        f" with {len(candidate_ids)} of the candidate"
    ]
    threshold = f"{report.threshold_percent:g} %"
    within = [r for r in report.results if not (r.regression or r.speedup)]
    for title, results in (
        (f"Regressions, slower by more than {threshold}:", report.regressions),
        (f"Suspicious speedups, faster by more than {threshold}:", report.speedups),
        ("Within the tolerance:", within),
    ):
        if results:
            lines.append(f"  {title}")
            lines.extend(_format_result(result) for result in results)
    for title, fullnames in (
        ("Only in the candidate:", report.candidate_only),
        ("Only in the history:", report.baseline_only),
    ):
        if fullnames:
            lines.append(f"  {title}")
            lines.extend(f"    {fullname}" for fullname in fullnames)
    return lines


def _summary(reports: list[ComparisonReport]) -> str:
    """
    One line counting the results of all `reports` by outcome.

    Regressions, speedups, and results within the tolerance are always
    counted.  Benchmarks and test sets held by one side only are counted if
    there are any.
    """

    def count(attribute: str) -> int:
        """The total length of the list `attribute` over all reports."""
        return sum(len(getattr(report, attribute)) for report in reports)

    def status(value: str) -> int:
        """The number of reports with the status `value`."""
        return sum(report.status == value for report in reports)

    regressions = count("regressions")
    speedups = count("speedups")
    parts = [
        _plural(regressions, "regression"),
        _plural(speedups, "speedup"),
        f"{count('results') - regressions - speedups} within the tolerance",
    ]
    for number, text in (
        (count("candidate_only"), "only in the candidate"),
        (count("baseline_only"), "only in the history"),
    ):
        if number:
            parts.append(f"{_plural(number, 'benchmark')} {text}")
    for number, text in (
        (status("missing_baseline"), "not in the history"),
        (status("missing_candidate"), "not in the candidate"),
    ):
        if number:
            parts.append(f"{_plural(number, 'test set')} {text}")
    return "Summary: " + ", ".join(parts)


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
    for report in reports:
        click.echo("\n".join(_format_report(report)))
    click.echo(_summary(reports))
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
    executions = sum(len(collection.executions) for collection in collections)
    click.echo(
        f"Stored {_plural(executions, 'runner execution')} of"
        f" {_plural(len(collections), 'test set')} in {history_root}"
    )
    for collection in collections:
        click.echo(
            f"  Test set {collection.test_set_id} of comparison target"
            f" {collection.comparison_target}: "
            + ", ".join(x.manifest.runner_execution_id for x in collection.executions)
        )
