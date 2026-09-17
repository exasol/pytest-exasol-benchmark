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
