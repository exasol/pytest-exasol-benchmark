from textwrap import dedent

import pytest

pytest_plugins = ["pytester"]


def test_missing_query_func_override_throws(pytester):
    test_code = dedent("""
        import pytest

        def test_missing_query_func_override_throws_pytester(exasol_benchmark):
            pass
    """)
    pytester.makepyfile(test_code)
    result = pytester.runpytest()
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        [
            "*NotImplementedError: Override of fixture 'query_func' not implemented*",
        ]
    )
