from textwrap import dedent

import pytest
from exasol.pytest_backend import (
    BACKEND_ONPREM,
    BACKEND_OPTION,
)


def test_data_producers(pytester):
    """Verifies both producers populate a real table in an Exasol database: the
    generated SQL is accepted, executes in order, and the SaaS variants skip."""
    test_code = dedent("""
        import pytest

        from exasol.pytest_benchmark import (
            exponential_row_data_producer,
            linear_row_data_producer,
        )

        SCHEMA_NAME = "PYTEST_BENCHMARK_DATA_PRODUCER"
        INPUT_TABLE_NAME = "SOURCE"
        INPUT_ROWS = 3

        @pytest.fixture()
        def query_func(pyexasol_connection):
            return pyexasol_connection.execute

        @pytest.fixture()
        def benchmark_schema(query_func):
            query_func(f'DROP SCHEMA IF EXISTS "{SCHEMA_NAME}" CASCADE')
            query_func(f'CREATE SCHEMA "{SCHEMA_NAME}"')
            query_func(f'CREATE TABLE "{SCHEMA_NAME}"."{INPUT_TABLE_NAME}" (ID DECIMAL(18,0))')
            for row_id in range(INPUT_ROWS):
                query_func(
                    f'INSERT INTO "{SCHEMA_NAME}"."{INPUT_TABLE_NAME}" VALUES ({row_id})'
                )
            yield SCHEMA_NAME
            query_func(f'DROP SCHEMA IF EXISTS "{SCHEMA_NAME}" CASCADE')

        @pytest.fixture()
        def output_table(query_func, benchmark_schema, request):
            table_name = f"TARGET_{request.function.__name__.upper()}"
            query_func(
                f'CREATE TABLE "{benchmark_schema}"."{table_name}" (ID DECIMAL(18,0))'
            )
            return table_name

        def count_rows(query_func, schema_name, table_name):
            return query_func(
                f'SELECT COUNT(*) FROM "{schema_name}"."{table_name}"'
            ).fetchval()

        def test_linear(query_func, benchmark_schema, output_table):
            '''Verifies the linear producer inserts the requested number of copies
            of the input rows in a single statement.'''
            executed = linear_row_data_producer(
                query_func,
                schema_name=benchmark_schema,
                output_table_name=output_table,
                input_table_name=INPUT_TABLE_NAME,
                factor=3,
            )
            assert len(executed) == 1
            assert count_rows(query_func, benchmark_schema, output_table) == 3 * INPUT_ROWS

        def test_exponential(query_func, benchmark_schema, output_table):
            '''Verifies the exponential producer doubles the output table in place,
            ending at 2 ** exponent copies of the input rows.'''
            executed = exponential_row_data_producer(
                query_func,
                schema_name=benchmark_schema,
                output_table_name=output_table,
                input_table_name=INPUT_TABLE_NAME,
                exponent=2,
            )
            assert len(executed) == 3
            assert count_rows(query_func, benchmark_schema, output_table) == 4 * INPUT_ROWS
    """)
    pytester.makepyfile(test_code)
    result = pytester.runpytest(BACKEND_OPTION, BACKEND_ONPREM)
    assert result.ret == pytest.ExitCode.OK
    # SaaS tests are skipped
    result.assert_outcomes(passed=2, skipped=2)
