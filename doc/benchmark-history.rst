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
never start with a dot.

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
    Represent comparison output.  A report identifies the baseline and
    candidate executions; each result describes one case in that comparison.

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
as GitHub's ``actions/download-artifact`` lays them out -- are stored as the
history by ``store_history``.  It copies the files of each artifact byte for
byte into the layout above:

.. code-block:: python

    from exasol.pytest_benchmark.history import store_history

    store_history(Path("artifacts"), Path("benchmark-history"))

Every artifact is validated before the history is changed.  A subdirectory
that is not a complete artifact -- for example one without ``manifest.json``,
without its benchmark file, or with an invalid manifest -- and two artifacts
sharing a runner identity are rejected, all of them reported in one error.
The same validation is available as ``collect_artifacts`` in
``exasol.pytest_benchmark.artifact``.

Reading the tree back groups the executions into one
``TestSetCollection`` per test set and comparison target:

.. code-block:: python

    from exasol.pytest_benchmark.history import load_history

    for collection in load_history(Path("benchmark-history")):
        print(collection.test_set_id, collection.comparison_target)
        for execution in collection.executions:
            print("  ", execution.manifest.runner_execution_id)

Normalized cases and comparison results
----------------------------------------

A ``NormalizedCase`` gives a case a stable identity and a compact, comparable
data payload::

    NormalizedCase(
        fullname="tests.test_queries::test_select",
        data={"mean": 1.23, "rounds": 10},
    )

The ``fullname`` is the pytest-benchmark case identity.  It must be unique
within a test-set collection.  Normalization is an in-memory comparison
concern; it does not change the raw ``benchmark.json`` artifact.

A ``ComparisonResult`` records the values for one case on both sides of a
comparison::

    ComparisonResult(
        fullname="tests.test_queries::test_select",
        baseline={"mean": 1.0},
        candidate={"mean": 1.2},
        attributes={"change_percent": 20.0},
    )

``baseline`` and ``candidate`` may contain any JSON value.  ``attributes`` is
an extension point for derived information such as percentage changes,
significance, or classification.  The models validate these values as JSON
data so they can be serialized without losing information.

The distinction is therefore::

    NormalizedCase   -> one normalized benchmark case
    ComparisonResult -> comparison of that case across two executions

Serialization
-------------

All public models inherit the common Pydantic configuration and retain the
``to_json()``/``from_json()`` convenience methods.  These methods use
Pydantic's JSON serialization internally.  Filesystem operations use
``pathlib.Path`` objects; for example::

    execution.write_to(Path("benchmark-history/target/set/run-1"))
    collections = load_history(Path("benchmark-history"))
