from textwrap import dedent

import pytest
from exasol.pytest_backend import (
    BACKEND_ONPREM,
    BACKEND_OPTION,
)

pytest_plugins = ["pytester"]


def test_query_cache_disabled(pytester):
    test_code = dedent("""
        import pytest

        GET_QUERY_CACHE_VALUE_SQL: str = "SELECT session_value FROM EXA_PARAMETERS WHERE parameter_name = 'QUERY_CACHE'"

        @pytest.fixture()
        def query_func(pyexasol_connection):
            return pyexasol_connection.execute

        @pytest.mark.parametrize("disable_query_cache,expected_query_cache_value", [(True, "OFF"), (False, "ON")])
        def test_query_cache_disabled_pytester(exasol_benchmark, pyexasol_connection, disable_query_cache, expected_query_cache_value):
            result = exasol_benchmark(pyexasol_connection.execute, (GET_QUERY_CACHE_VALUE_SQL,), disable_query_cache=disable_query_cache)
            # within the 'exasol_benchmark' context the query cache should have the expected value
            assert result.fetchval() == expected_query_cache_value
            # outside the 'exasol_benchmark' context the query cache should have its default value
            actual_query_cache = pyexasol_connection.execute(GET_QUERY_CACHE_VALUE_SQL).fetchval()
            assert actual_query_cache == "ON"
    """)
    pytester.makepyfile(test_code)
    result = pytester.runpytest(BACKEND_OPTION, BACKEND_ONPREM)
    assert result.ret == pytest.ExitCode.OK
    # SaaS tests are skipped
    result.assert_outcomes(passed=2, skipped=2)
