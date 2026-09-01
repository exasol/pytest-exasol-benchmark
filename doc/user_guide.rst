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

Benchmark artifacts
-------------------

Benchmark results are stored as versioned, Git-trackable artifacts.  The
on-disk layout, the public models, and the compatibility rules are described
in:

.. toctree::
   :maxdepth: 1

   benchmark-history
