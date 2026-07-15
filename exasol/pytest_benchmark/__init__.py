from contextlib import contextmanager
from importlib.metadata import version

__version__ = version("pytest_exasol_benchmark")
import logging
from collections.abc import Callable
from typing import (
    Any,
    TypeAlias,
)

import pytest

logger = logging.getLogger(__name__)

QueryResult: TypeAlias = Any
QueryFunc: TypeAlias = Callable[[str], QueryResult]


@pytest.fixture
def query_func() -> QueryFunc:
    """
    The fixture shall return a function which can be used to execute SQL queries.
    The user has to override this fixture.
    """
    raise NotImplementedError("Override of fixture 'query_func' not implemented")


def get_enable_query_cache_sql() -> str:
    return "alter session set query_cache='on'"


def get_disable_query_cache_sql() -> str:
    return "alter session set query_cache='off'"


@contextmanager
def disable_query_cache_session(query_func: QueryFunc, disable_query_cache: bool):
    if disable_query_cache:
        query_func(get_disable_query_cache_sql())
    yield
    if disable_query_cache:
        query_func(get_enable_query_cache_sql())


@pytest.fixture
def exasol_benchmark(benchmark, query_func: QueryFunc):
    def run_benchmark(
        target: Callable,
        args: tuple = (),
        rounds=1,
        warmup_rounds=0,
        iterations=1,
        disable_query_cache: bool = True,
    ):
        with disable_query_cache_session(query_func, disable_query_cache):
            return benchmark.pedantic(
                target=target,
                args=args,
                rounds=rounds,
                warmup_rounds=warmup_rounds,
                iterations=iterations,
            )

    return run_benchmark
