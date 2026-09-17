from textwrap import dedent

import pytest
from exasol.pytest_backend import (
    BACKEND_ONPREM,
    BACKEND_OPTION,
)


def test_table_size(pytester):
    """Verifies the table size inspector against a real Exasol database: the
    generated SQL is accepted, reports the size of a created table, fails for a
    missing one, and the SaaS variants skip."""
    test_code = dedent('''
        from datetime import datetime

        import pytest

        from exasol.pytest_benchmark import (
            get_table_size,
            linear_row_data_producer,
        )

        SCHEMA_NAME = "PYTEST_BENCHMARK_TABLE_SIZE"
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

        def test_size_of_created_table(query_func, benchmark_schema, output_table):
            """Verifies the inspector reports the size of an existing table, and that
            the reported size follows the rows added to it."""
            empty = get_table_size(query_func, benchmark_schema, output_table)
            assert empty.row_count == 0
            assert isinstance(empty.last_commit, datetime)

            linear_row_data_producer(
                query_func,
                schema_name=benchmark_schema,
                output_table_name=output_table,
                input_table_name=INPUT_TABLE_NAME,
                factor=1,
            )

            filled = get_table_size(query_func, benchmark_schema, output_table)
            assert filled.row_count == INPUT_ROWS
            assert filled.raw_bytes > 0
            assert filled.mem_bytes > 0
            assert filled.raw_bytes >= empty.raw_bytes
            assert filled.mem_bytes >= empty.mem_bytes
            assert filled.last_commit >= empty.last_commit

        def test_missing_table(query_func, benchmark_schema):
            """Verifies a table which does not exist fails clearly instead of
            reporting a size."""
            with pytest.raises(ValueError, match="was not found or is not accessible"):
                get_table_size(query_func, benchmark_schema, "DOES_NOT_EXIST")
    ''')
    pytester.makepyfile(test_code)
    result = pytester.runpytest(BACKEND_OPTION, BACKEND_ONPREM)
    assert result.ret == pytest.ExitCode.OK
    # SaaS tests are skipped
    result.assert_outcomes(passed=2, skipped=2)
