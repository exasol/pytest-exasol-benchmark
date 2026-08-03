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

The checked-out tree is the complete baseline for the current commit.  Git
provides the history; loaders do not require revision directories or aggregate
run files.  Runner identities are the tuple of test-set ID, comparison target,
and runner-execution ID, and duplicates are rejected.

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
