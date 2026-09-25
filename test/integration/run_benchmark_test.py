from textwrap import dedent

import pytest


def test_run_benchmark(pytester, backend_args):
    test_code = dedent("""
        import pytest
        import random
        import time

        @pytest.fixture()
        def query_func(pyexasol_connection):
            return pyexasol_connection.execute

        def do_something():
            time.sleep(random.randint(1, 99) / 1000.0)

        def test_run_benchmark_pytester(exasol_benchmark, pyexasol_connection):
            exasol_benchmark(do_something)
    """)
    pytester.makepyfile(test_code)
    result = pytester.runpytest(*backend_args)
    assert result.ret == pytest.ExitCode.OK
    # the tests for the other backend are skipped
    result.assert_outcomes(passed=1, skipped=1)
    result.stdout.fnmatch_lines(
        [
            "*benchmark: 1 tests*",
        ]
    )
