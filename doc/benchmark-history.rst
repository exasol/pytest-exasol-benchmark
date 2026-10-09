Benchmark artifact and history format
======================================

The public models in ``exasol.pytest_benchmark.models`` use schema version
``1``.  A runner execution is stored below the current checkout's
``benchmark-history`` directory::

    benchmark-history/<comparison-target>/<test-set-id>/<runner-execution-id>/
        manifest.json
        benchmark.json

``manifest.json`` contains ``schema_version``, ``test_set_id``,
``comparison_target``, ``runner_execution_id``, ``source_revision``,
``platform`` (at least ``os`` and ``architecture``), ``attributes``, and the
``benchmark_file`` name.  ``benchmark.json`` is the unchanged pytest-benchmark
output.  ``attributes`` is an extensible JSON object for database versions,
implementation identifiers, deployment details, and similar context.

A *test set* is a fixed selection of benchmarks -- pytest tests with their
parameters and data sizes -- which is always run as a whole.  Every runner
execution of a test set yields one sample of the same benchmarks, identified
by their pytest-benchmark ``fullname``.  A code change or a dependency update
does not change the test set; it changes ``source_revision`` or
``attributes``.

The checked-out tree is the complete baseline for the current revision: every
``manifest.json``/``benchmark.json`` pair present in the working copy belongs
to that revision's baseline, and nothing else does.  Storing a benchmark run
writes one directory per runner execution -- holding the manifest and the
``benchmark.json`` of that single test run -- and replaces the whole
``<comparison-target>/<test-set-id>`` subtree of each stored test set, so the
runner executions of an earlier run do not remain in the baseline.  Subtrees
of test sets which are not part of the stored run are left untouched.

If the performance behavior has changed and the new behavior is the accepted
one, a new baseline is created by running the benchmark and committing the new
result as the new baseline.  The previous numbers are not lost: the baseline of
an earlier revision is recovered by checking that revision out.  Git provides
the history; loaders do not require revision directories or aggregate run
files.  Runner identities are the tuple of test-set ID, comparison target, and
runner-execution ID, and duplicates are rejected while loading and storing.
Entries whose names start with a dot are ignored while loading; identifiers
never start with a dot.  Neither the history root nor anything below it may be
a symbolic link, so loading and storing never read or replace files outside
it.  Every directory below the root which holds files, or no directories, is
read as a runner execution, so one missing its ``manifest.json`` is rejected
rather than ignored.

Keep versions, such as the database version, in ``attributes`` rather than in
the test-set ID or the comparison target.  Then an upgrade replaces the
baseline when its results are stored, instead of creating a second baseline
next to the old one.

Schema versions are fields in JSON documents.  Backwards-compatible public
model additions may use the same major schema version.  Incompatible changes
require a new major schema version, with readers supporting migration while
old artifacts remain in use.

Public models
-------------

The models in ``exasol.pytest_benchmark.models`` describe different layers of
benchmark data:

``PlatformMetadata``
    Identifies the runner platform, including its operating system and
    architecture.

``ArtifactManifest``
    Describes one runner execution and its provenance.  The combination of
    ``test_set_id``, ``comparison_target``, and ``runner_execution_id`` is the
    execution identity.  Project-specific information, such as database
    versions or implementation IDs, belongs in ``attributes``.

``RunnerExecution``
    Combines an artifact manifest with the raw pytest-benchmark document.  The
    raw document is kept in ``benchmark.json`` and is not normalized or
    rewritten by the model.

``TestSetCollection``
    Groups executions for one test set and comparison target.  It also holds
    normalized cases keyed by their pytest-benchmark ``fullname``.

``ComparisonReport`` and ``ComparisonResult``
    Represent comparison output.  A report describes the comparison of one
    test set and comparison target, naming the runner executions aggregated on
    each side; each result compares one case.

Example artifact
~~~~~~~~~~~~~~~~

A ``manifest.json`` written by ``RunnerExecution.write_to()`` looks like this:

.. code-block:: json

    {
      "schema_version": 1,
      "test_set_id": "tpch-sf10",
      "comparison_target": "onprem-standard",
      "runner_execution_id": "run-1",
      "source_revision": "8f12ab4",
      "platform": {
        "os": "ubuntu-24.04",
        "architecture": "x86_64",
        "python_version": "3.12.7"
      },
      "attributes": {"database": {"version": "8.31.0"}},
      "benchmark_file": "benchmark.json"
    }

The matching Python code that produces the artifact directory:

.. code-block:: python

    import json
    from pathlib import Path

    from exasol.pytest_benchmark import (
        ArtifactManifest,
        PlatformMetadata,
        RunnerExecution,
    )

    execution = RunnerExecution(
        manifest=ArtifactManifest(
            test_set_id="tpch-sf10",
            comparison_target="onprem-standard",
            runner_execution_id="run-1",
            source_revision="8f12ab4",
            platform=PlatformMetadata(
                os="ubuntu-24.04",
                architecture="x86_64",
                python_version="3.12.7",
            ),
            attributes={"database": {"version": "8.31.0"}},
        ),
        benchmark=json.loads(Path(".benchmarks/output.json").read_text()),
    )
    execution.write_to(
        Path("benchmark-history/onprem-standard/tpch-sf10/run-1")
    )

The ``package`` command of the ``pytest-exasol-benchmark`` executable creates
such a directory from the JSON written by ``pytest --benchmark-json``.  Unlike
``RunnerExecution.write_to()``, which serializes the parsed document again, it
copies the JSON byte for byte and derives ``platform`` from its
``machine_info``.  The structure it requires from the JSON is described by the
``BenchmarkDocument`` model.  The same validation is available in Python:

.. code-block:: python

    from exasol.pytest_benchmark.artifact import (
        package_artifact,
        validate_artifact,
    )

    package_artifact(
        Path(".benchmarks/output.json"),
        Path("artifact"),
        test_set_id="tpch-sf10",
        comparison_target="onprem-standard",
        runner_execution_id="run-1",
        source_revision="8f12ab4",
    )
    execution = validate_artifact(Path("artifact"))

Packaged artifacts downloaded side by side -- one artifact per subdirectory,
as GitHub's ``actions/download-artifact`` lays them out when it downloads all
artifacts of a run, without ``name`` and ``merge-multiple`` -- are stored as
the history by ``store_history``.  It copies the files of each artifact byte
for byte into the layout above:

.. code-block:: python

    from exasol.pytest_benchmark.history import store_history

    store_history(Path("artifacts"), Path("benchmark-history"))

Every artifact is validated before the history is changed.  A subdirectory
that is not a complete artifact -- for example one without ``manifest.json``,
without its benchmark file, or with an invalid manifest -- and two artifacts
sharing a runner identity are rejected, all of them reported in one error.
Symbolic links, for the artifacts directory or inside it, are rejected as
well.  Entries whose names start with a dot, such as ``.DS_Store`` files, are
ignored.
The same validation is available as ``collect_artifacts`` in
``exasol.pytest_benchmark.artifact``.

The artifacts are first copied to the staging directory
``benchmark-history/.store`` and then moved in place, one test set after the
other.  Only one store may write the history at a time: while the staging
directory exists, a second store and ``load_history`` reject the history.  A
store which is killed while moving the test sets in place leaves the staging
directory behind, and possibly a partially replaced history.  Restore the
history from Git, for example with ``git restore`` and ``git clean``, and remove
the staging directory.  Serialize the jobs which store and load the same
checkout, for example with a GitHub Actions ``concurrency`` group: a store
which starts and ends while the history is loaded is not detected.

Reading the tree back groups the executions into one
``TestSetCollection`` per test set and comparison target:

.. code-block:: python

    from exasol.pytest_benchmark.history import load_history

    for collection in load_history(Path("benchmark-history")):
        print(collection.test_set_id, collection.comparison_target)
        for execution in collection.executions:
            print("  ", execution.manifest.runner_execution_id)

The artifacts of a benchmark run which is to be compared with the history are
collected by ``collect_candidates`` in ``exasol.pytest_benchmark.artifact``,
the counterpart of ``load_history``.  They are validated like the input of
``store_history``, see ``collect_artifacts``.  Any download step works which
puts one artifact per subdirectory; the names of the subdirectories do not
matter, each artifact's identity comes from its manifest.  The function
groups the runner executions into one ``TestSetCollection`` per test set and
comparison target, keeping every test set and runner sample:

.. code-block:: python

    from exasol.pytest_benchmark.artifact import collect_candidates

    for collection in collect_candidates(Path("artifacts")):
        print(collection.test_set_id, len(collection.executions))

Invalid and incomplete artifacts, and runner identities occurring twice, are
reported in one error before anything is compared.  Whether the runner
executions of a test set contain the same benchmarks is not checked here:
matching them is part of the comparison.

Comparing with the history
--------------------------

``compare_with_history`` in ``exasol.pytest_benchmark.comparison`` compares
the collected candidate with the history of the current checkout.  It reads
both and writes nothing.  Git is not consulted: whatever ``benchmark-history``
holds in the working tree is the baseline, whichever revision it was stored
at.

.. code-block:: python

    from exasol.pytest_benchmark.comparison import compare_with_history

    for report in compare_with_history(
        Path("artifacts"), Path("benchmark-history"), threshold_percent=10.0
    ):
        print(report.test_set_id, report.comparison_target, report.status)
        for result in report.regressions:
            change = result.change_percent
            # No percentage for a baseline too close to zero, see below.
            text = "n/a" if change is None else f"{change:+.1f} %"
            print(f"  {result.fullname}: {text}")

``compare_collections`` does the same for collections already loaded, and
``aggregate_collection`` aggregates a single collection.

Test sets are matched by test set ID and comparison target.  Each side of a
test set is reduced to one value per benchmark in two steps.  First, each
runner execution yields the median of the benchmark's round timings, see the
normalization below.  Then these runner medians are combined into their
median.  The number of runner executions may differ between the sides.

The runner executions of a test set are parallel runs of the same benchmarks
on the same revision, for example the jobs of a GitHub Actions matrix, so
they hold the same benchmarks.  A runner execution lacking a benchmark which
another one of its side holds is invalid input, in the history as well as in
the candidate.

.. important::

   A runner execution whose pytest run failed must not produce an artifact.
   pytest-benchmark leaves a benchmark out of its JSON if the benchmarked
   function raises, but keeps it if the test fails afterwards, for example in
   an ``assert`` on the result, so the JSON does not tell whether its tests
   passed.  In GitHub Actions, this is the default: once the ``pytest`` step
   fails, the following ``package`` and ``upload-artifact`` steps of the job
   are skipped.  Do not run them anyway, for example with ``if: always()``
   on these steps or ``continue-on-error: true`` on the ``pytest`` step: the
   artifacts of failed runs make the comparison unpredictable, for example
   by turning a failed benchmark into one which looks removed from the test
   set.

The benchmarks both sides of a test set hold are compared.  The change of a
benchmark is ``(candidate - baseline) / baseline * 100`` percent, negative for
a speedup.  It is a regression if the change is greater than the threshold,
``10`` percent by default; a change equal to the threshold within rounding is
not.  A baseline not greater than ``near_zero_seconds``, one millisecond by
default, is too close to zero for a meaningful percentage: the benchmark is
compared as if the baseline was ``near_zero_seconds``, and its
``change_percent`` is ``None``.  So a candidate not slower than
``near_zero_seconds`` is never a regression, and timings varying around it
are compared with the threshold like any others.

There is one ``ComparisonReport`` per test set and comparison target of either
side.  Its ``status`` tells whether the test set was compared:

``compared``
    Both sides hold the test set.  ``results`` compares each benchmark both
    sides hold.  ``baseline_only`` lists the benchmarks only the history
    holds, for example because they were removed from the test set, and
    ``candidate_only`` those only the candidate holds, for example because they
    were added.  They are compared once the test set is stored as the history
    again.
``missing_baseline``
    The history holds no runner execution of the test set, for example
    because the test set is new.
``missing_candidate``
    The candidate holds no runner execution of the test set.

Each report lists the runner executions aggregated on each side.  Only the
compared benchmarks can be regressions; test sets and benchmarks held by one
side only are reported, but never classified as a regression.  The source
revision, platform, and attributes of the runner executions are not compared.
Invalid input is reported in one ``ArtifactError`` listing the problems of
both sides, each prefixed with ``history`` or ``candidate``: runner executions
lacking benchmarks, benchmark documents which cannot be normalized, and, for
``compare_collections``, a test set occurring twice.

Normalized cases and comparison results
----------------------------------------

A ``NormalizedCase`` gives a case a stable identity and a compact, comparable
data payload::

    NormalizedCase(
        fullname="tests/test_queries.py::test_select[10]",
        data={
            "median": 0.0012,
            "min": 0.0011,
            "max": 0.0019,
            "mean": 0.0013,
            "rounds": 10,
        },
    )

The ``fullname`` is the pytest-benchmark case identity.  It must be unique
within a test-set collection.  Normalization is an in-memory comparison
concern; it does not change the raw ``benchmark.json`` artifact.

``normalize_execution`` in ``exasol.pytest_benchmark.normalization`` turns the
benchmark document of one runner execution into one ``NormalizedCase`` per
benchmark, keyed by ``fullname`` in document order.  Read the document with
``validate_artifact`` or ``load_history`` rather than ``json.load``: they
reject files which are empty, not UTF-8 encoded, or contain numbers which are
not finite.  ``normalize_benchmark`` does the same for a parsed
``pytest --benchmark-json`` document, naming its source in error messages.

.. code-block:: python

    from pathlib import Path

    from exasol.pytest_benchmark.artifact import validate_artifact
    from exasol.pytest_benchmark.normalization import normalize_execution

    cases = normalize_execution(validate_artifact(Path("artifact")))
    median = cases["tests/test_queries.py::test_select[10]"].data["median"]

A case retains the ``median``, ``min``, ``max``, and ``mean`` of the round
timings, in seconds, and the number of ``rounds`` from the benchmark's
``stats``; all other values of the document are dropped.  Each of them is
required: the timings have to be finite non-negative numbers, with the median
and the mean between the minimum and the maximum, and ``rounds`` has to be a
positive whole number.

A document which is not structured as described by ``BenchmarkDocument`` --
for example one without benchmarks or with a ``fullname`` twice -- is
rejected first, with an ``ArtifactError`` describing its structure.  Only the
statistics of a well-structured document are checked: every benchmark missing
a retained statistic or holding an invalid or inconsistent one is reported in
one ``ArtifactError``, one per line.

Normalization works on one runner execution.  The executions of a test set
sample the same benchmarks, so the comparison aggregates their cases, for
example by their median, rather than adding each execution's cases to the
``TestSetCollection``.

A ``ComparisonResult`` records the aggregated medians of one case on both
sides of a comparison, in seconds, its change, and whether it is a
regression::

    ComparisonResult(
        fullname="tests/test_queries.py::test_select[10]",
        baseline=1.0,
        candidate=1.2,
        change_percent=20.0,
        regression=True,
    )

``attributes`` is an extension point for further derived information.  The
models validate it as JSON data so it can be serialized without losing
information.  A ``ComparisonReport`` holds the results of one test set and
comparison target, see `Comparing with the history`_.

The distinction is therefore::

    NormalizedCase   -> one normalized benchmark case
    ComparisonResult -> comparison of that case between baseline and candidate

Serialization
-------------

All public models inherit the common Pydantic configuration and retain the
``to_json()``/``from_json()`` convenience methods.  These methods use
Pydantic's JSON serialization internally.  Filesystem operations use
``pathlib.Path`` objects; for example::

    execution.write_to(Path("benchmark-history/target/set/run-1"))
    collections = load_history(Path("benchmark-history"))
