.. _user_guide:

:octicon:`person` User Guide
============================
``pytest-exasol-benchmark`` provides fixtures and helper function to perform benchmarking operations.

.. note::
   The project covers regular Exasol tables only.  Virtual schemas and virtual tables
   are out of scope: they are read-only, so the data producers cannot populate them,
   and Exasol reports no row count for them in ``EXA_ALL_TABLES``.

Fixtures
--------

- ``query_func``: **you must override this fixture** with your SQL execution hook.
- ``exasol_benchmark``: a wrapper around ``pytest-benchmark`` that runs the benchmarked callable with Exasol query cache handling.

``query_func``
~~~~~~~~~~~~~~

The package only provides a placeholder ``query_func`` fixture.
**Override it in your test suite before using ``exasol_benchmark``**; otherwise it raises ``NotImplementedError``.

Implement it to return a callable that accepts a SQL string and executes it against your Exasol connection:

.. code-block:: python

   import pytest

   @pytest.fixture()
   def query_func(pyexasol_connection):
       return pyexasol_connection.execute

The helpers which only execute statements, such as the data producers, ignore what the
callable returns.  The helpers which read data back, such as ``get_table_size``, need
the query result: an iterable of rows, where each row is a sequence of column values.
``pyexasol``'s ``execute`` satisfies both, as long as the connection keeps the default
fetch mode: with ``fetch_dict=True`` its rows are dictionaries, which the helpers
reading data back do not accept.

``exasol_benchmark``
~~~~~~~~~~~~~~~~~~~~

By default, it disables the query cache for the current session before the benchmark and re-enables it afterwards:
Set ``disable_query_cache=False`` to leave the session setting unchanged.

.. note::
   The benchmark function needs to use the same session as ``query_func``,
   to respect the session settings managed by the ``exasol_benchmark`` fixture.

E.g., use it to benchmark SQL queries that interact with an Exasol database:

.. code-block:: python

   def test_sql_query_performance(exasol_benchmark, pyexasol_connection):
       exasol_benchmark(
           pyexasol_connection.execute,
           ("SELECT * FROM customers;",),
       )

Data generators
---------------

The package provides SQL generators for benchmark data:

Schema and table names are always rendered as quoted identifiers, and are used
exactly as given, so ``"target"`` in Python becomes ``"target"`` in the SQL and keeps
its case.  Enclosing double quotes are stripped first, so ``'"target"'`` also resolves to
same as ``"target"``:

.. list-table::
   :header-rows: 1

   * - Passed as
     - Rendered as
   * - ``"target"``
     - ``"target"``
   * - ``'"target"'``
     - ``"target"``
   * - ``"my table"``
     - ``"my table"``

A name may therefore contain any character; a double quote inside it is escaped and
can never end the identifier and change the statement.  Passing an empty name raises a
``ValueError``.

Note that Exasol converts unquoted identifiers to uppercase.  A table
created by ``CREATE TABLE bench.target`` is called ``TARGET``, so it has to be passed
as ``"TARGET"``, not ``"target"``.

``Linear growth``
~~~~~~~~~~~~~~~~~
.. code-block:: python

   linear_row_sql_data_generator(
       schema_name: str,
       output_table_name: str,
       input_table_name: str,
       factor: int,
       max_unions: int = MAX_UNIONS,
   ) -> list[str]

Copies input rows ``factor`` times; ``max_unions`` limits copies per statement.

.. list-table::
   :header-rows: 1

   * - ``factor``
     - Copies of the input rows
   * - 1
     - 1
   * - 2
     - 2
   * - 3
     - 3

Example: generate SQL that inserts three copies of ``source`` into ``target``:

.. code-block:: python

   statements = linear_row_sql_data_generator(
       schema_name="BENCHMARK",
       output_table_name="target",
       input_table_name="source",
       factor=3,
   )
   for statement in statements:
       query_func(statement)

``Exponential growth``
~~~~~~~~~~~~~~~~~~~~~~
.. code-block:: python

   exponential_row_sql_data_generator(
       schema_name: str,
       output_table_name: str,
       input_table_name: str,
       exponent: int = 1,
   ) -> list[str]

Copies the input once, then doubles the output ``exponent`` times, producing ``2 ** exponent`` copies of the input rows.

.. list-table::
   :header-rows: 1

   * - ``exponent``
     - Copies of the input rows
   * - 1
     - 2
   * - 2
     - 4
   * - 3
     - 8

Example: generate SQL that grows ``target`` to eight copies of ``source``:

.. code-block:: python

   statements = exponential_row_sql_data_generator(
       schema_name="BENCHMARK",
       output_table_name="target",
       input_table_name="source",
       exponent=3,
   )
   for statement in statements:
       query_func(statement)

Data producers
--------------

The data producers execute the generated SQL statements, in the generated order,
through the ``query_func`` you supplied:

``linear_row_data_producer``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. code-block:: python

   linear_row_data_producer(
       query_func: QueryFunc,
       schema_name: str,
       output_table_name: str,
       input_table_name: str,
       factor: int,
       max_unions: int = MAX_UNIONS,
   ) -> list[str]

Example: insert three copies of ``source`` into ``target``:

.. code-block:: python

   def test_query_performance(exasol_benchmark, query_func):
       linear_row_data_producer(
           query_func,
           schema_name="BENCHMARK",
           output_table_name="target",
           input_table_name="source",
           factor=3,
       )

``exponential_row_data_producer``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. code-block:: python

   exponential_row_data_producer(
       query_func: QueryFunc,
       schema_name: str,
       output_table_name: str,
       input_table_name: str,
       exponent: int = 1,
   ) -> list[str]

Example: grow ``target`` to eight copies of ``source``:

.. code-block:: python

   def test_query_performance(exasol_benchmark, query_func):
       exponential_row_data_producer(
           query_func,
           schema_name="BENCHMARK",
           output_table_name="target",
           input_table_name="source",
           exponent=3,
       )

Both functions return the list of executed SQL statements.

.. note::
   The producers do not create, truncate, or drop any table --- the output table must
   already exist and is expected to be empty.  The generated statements are ``INSERT``
   statements, so calling a producer again on a non-empty output table adds to the rows
   already present instead of replacing them.

Table size
----------

``get_table_size`` reads the current size of an existing, accessible table from the
Exasol system tables ``SYS.EXA_ALL_TABLES`` and ``SYS.EXA_ALL_OBJECT_SIZES``, which it
joins through the table's object ID:

.. code-block:: python

   get_table_size(
       query_func: QueryFunc,
       schema_name: str,
       table_name: str,
   ) -> TableSize

It returns a frozen ``TableSize`` dataclass:

.. list-table::
   :header-rows: 1

   * - Attribute
     - Meaning
   * - ``row_count``
     - Number of rows in the table
   * - ``raw_bytes``
     - Uncompressed data volume in bytes
   * - ``mem_bytes``
     - Compressed data volume in bytes
   * - ``last_commit``
     - ``datetime`` of the most recent modification

Example: measure how much a benchmark table grew:

.. code-block:: python

   def test_query_performance(exasol_benchmark, query_func):
       before = get_table_size(query_func, "BENCHMARK", "TARGET")
       linear_row_data_producer(
           query_func,
           schema_name="BENCHMARK",
           output_table_name="TARGET",
           input_table_name="SOURCE",
           factor=3,
       )
       after = get_table_size(query_func, "BENCHMARK", "TARGET")
       assert after.row_count > before.row_count

Unlike the data generators, the schema and table name are not rendered as identifiers:
the system tables hold them as string values, so they are rendered as string literals.
They are still used exactly as given, only stripped of enclosing double quotes, and an
empty name raises a ``ValueError``.  Since Exasol stores the name of an unquoted
identifier uppercase, a table created by ``CREATE TABLE bench.target`` has to be
looked up as schema ``BENCH`` and table ``TARGET``.

A table which does not exist or is not accessible, and a query result which does not
have the expected shape, raise a ``ValueError`` naming the table and the problem.

.. note::
   Exasol reports the sizes and the last-commit timestamp as of the last ``COMMIT``, so
   a table modified in an open transaction is measured as it was before.  The sizes in
   ``SYS.EXA_ALL_OBJECT_SIZES`` are calculated recursively, which is not free on a
   database with many objects.

``get_table_size_sql`` returns the same statement without executing it, for example to
log or to run it yourself:

.. code-block:: python

   get_table_size_sql(
       schema_name: str,
       table_name: str,
   ) -> str

Benchmark artifacts
-------------------

Benchmark results are stored as versioned, Git-trackable artifacts.  The
on-disk layout, the public models, and the compatibility rules are described
in:

.. toctree::
   :maxdepth: 1

   benchmark-history

Command line interface
----------------------

The package provides the ``pytest-exasol-benchmark`` command-line tool for
processing benchmark artifacts.  It does not run pytest or execute benchmarks.
To generate benchmark data, run pytest directly with the ``--benchmark-json``
option, then use ``pytest-exasol-benchmark`` with the commands below to process
the resulting JSON file.

``package``
    Packages the JSON of one pytest run as a portable runner artifact.  The
    options ``--benchmark-json``, ``--test-set-id``, ``--comparison-target``,
    ``--runner-execution-id``, ``--source-revision``, and ``--output-dir`` are
    required.  The output directory receives ``manifest.json`` and
    ``benchmark.json``, a byte-identical copy of the pytest-benchmark JSON.
    The manifest holds the given IDs and the runner platform, which is taken
    from the ``machine_info`` of the JSON (``system``, ``machine``, and
    ``python_version``).  The output directory is created if missing and has
    to be empty otherwise.  The input is validated before anything is written.
    A failed write leaves nothing behind, and as ``manifest.json`` is written
    last, an interrupted one never leaves an artifact that looks complete.  Malformed JSON, JSON without benchmarks, and an
    invalid ``machine_info`` are rejected with an error naming the problem.

    .. code-block:: shell

        pytest --benchmark-json=output.json
        pytest-exasol-benchmark package \
            --benchmark-json output.json \
            --test-set-id tpch-sf10 \
            --comparison-target onprem-standard \
            --runner-execution-id run-1 \
            --source-revision "$(git rev-parse --short HEAD)" \
            --output-dir artifact

``compare``
    Compares the runner artifacts in a directory with the benchmark history of
    the current checkout (``--history-root``, default ``benchmark-history``)
    and prints one report per test set, see :doc:`benchmark-history` for how
    the runner executions are aggregated and compared.  A benchmark slower
    than ``--threshold`` percent (default ``10``) is a regression, one faster
    by more than the threshold a speedup.  Regressions, speedups, and the
    benchmarks within the threshold are listed in separate sections, followed
    by the benchmarks and test sets held by one side only, and a summary.
    ``n/a`` stands for a change which is not reported because the baseline is
    too close to zero.  ``--json-output`` additionally writes the reports to a
    file as a JSON list of ``ComparisonReport`` objects.  Nothing is written
    to the history.

    .. warning::

       An existing ``--json-output`` file is removed before anything else, so
       a failed comparison leaves no outdated reports behind.  It is removed
       even if the comparison then fails, so never point the option at a file
       you want to keep, such as the ``--benchmark-json`` output of pytest.

    .. code-block:: shell

        pytest-exasol-benchmark compare artifacts --json-output reports.json

    .. code-block:: text

        Test set tpch-sf10 of comparison target onprem-standard: compared 3 history runner executions with 3 of the candidate
          Regressions, slower by more than 10 %:
              +20.0 %  1 s -> 1.2 s  tests/test_queries.py::test_select[10]
          Speedups, faster by more than 10 %:
              -35.0 %  2 s -> 1.3 s  tests/test_queries.py::test_join[10]
          Within the threshold:
               +2.0 %  0.5 s -> 0.51 s  tests/test_queries.py::test_count[10]
          Only in the candidate:
            tests/test_queries.py::test_group_by[10]
        Summary: 1 regression, 1 speedup, 1 within the threshold, 1 benchmark only in the candidate

    The exit status is ``0`` if no benchmark is a regression, ``1`` if one is,
    and ``2`` if the comparison could not be done, for example because an
    artifact or the history is invalid, or because the history holds none of
    the test sets of the artifacts, for example because it is missing.
    Without a compared test set nothing could be a regression, so a mistyped
    ``--history-root``, test set ID, or comparison target would otherwise
    pass.  For the first benchmark run of a project, use ``store`` instead to
    create the history.  Speedups and data held by one side only, such as a new test
    set added to an existing history or a removed benchmark, do not fail the
    comparison.

``store``
    Stores the runner artifacts in a directory as the benchmark history below
    ``--history-root``, replacing the stored runner executions of each test
    set they hold.  Everything is validated before the history is changed: an
    incomplete or invalid artifact, two artifacts with the same runner
    identity, runner executions of a test set holding different benchmarks,
    and benchmarks with invalid statistics are rejected with exit status
    ``2``, and nothing is stored.

    .. code-block:: shell

        pytest-exasol-benchmark store artifacts

Every command exits with status ``2`` if it could not be done, for example
because of invalid input.  ``pytest-exasol-benchmark --help`` and
``pytest-exasol-benchmark <command> --help`` describe the available options.
