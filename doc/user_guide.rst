.. _user_guide:

:octicon:`person` User Guide
============================
``pytest-exasol-benchmark`` provides fixtures and helper function to perform benchmarking operations.

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

Benchmark artifacts
-------------------

Benchmark results are stored as versioned, Git-trackable artifacts.  The
on-disk layout, the public models, and the compatibility rules are described
in:

.. toctree::
   :maxdepth: 1

   benchmark-history
