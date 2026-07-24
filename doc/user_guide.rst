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

E.g., use it to benchmark SQL queries that interact with an Exasol database:

.. code-block:: python

   def test_sql_query_performance(exasol_benchmark, pyexasol_connection):
       exasol_benchmark(
           pyexasol_connection.execute,
           ("SELECT * FROM customers;",),
       )

By default, it disables the query cache before the benchmark and re-enables it afterwards:
Set ``disable_query_cache=False`` to leave the session setting unchanged.

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
