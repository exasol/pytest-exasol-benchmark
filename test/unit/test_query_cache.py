import pytest

from exasol.pytest_benchmark import (
    disable_query_cache_session,
    get_disable_query_cache_sql,
    get_enable_query_cache_sql,
)


def test_re_enables_query_cache_after_success():
    queries = []
    with disable_query_cache_session(queries.append, True):
        queries.append("benchmark")
    assert queries == [
        get_disable_query_cache_sql(),
        "benchmark",
        get_enable_query_cache_sql(),
    ]


def test_re_enables_query_cache_when_benchmark_fails():
    queries = []
    with pytest.raises(RuntimeError, match="benchmark failed"):
        with disable_query_cache_session(queries.append, True):
            raise RuntimeError("benchmark failed")
    assert queries == [get_disable_query_cache_sql(), get_enable_query_cache_sql()]


def test_keeps_query_cache_untouched_if_not_disabled():
    queries = []
    with disable_query_cache_session(queries.append, False):
        queries.append("benchmark")
    assert queries == ["benchmark"]
