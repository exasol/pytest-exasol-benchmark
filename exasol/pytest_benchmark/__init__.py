from contextlib import contextmanager
from importlib.metadata import version

from sqlglot import exp

__version__ = version("pytest_exasol_benchmark")
import logging
from collections.abc import Callable
from typing import (
    Any,
    TypeAlias,
)

import pytest
from sqlglot.expressions import (
    Query,
    Select,
)

logger = logging.getLogger(__name__)

QueryResult: TypeAlias = Any
QueryFunc: TypeAlias = Callable[[str], QueryResult]

MAX_UNIONS: int = 100


def linear_row_sql_data_generator(
    schema_name: str,
    output_table_name: str,
    input_table_name: str,
    factor: int,
    max_unions: int = MAX_UNIONS,
) -> list[str]:
    """
    Generate SQL statements that copy rows from `schema.input_table_name` to `schema.output_table_name`
    `factor` times using UNION ALL. For each `max_unions` a new SQL statement is added to the list.

    Returns a list of SQL statements.
    Example:
        factor=3,   max_unions=100 -> 1 SQL statement
        factor=150, max_unions=100 -> 3 SQL statements: 150 + 50
    """
    if factor < 1:
        raise ValueError("factor must be greater than 0")
    if max_unions < 1 or max_unions > MAX_UNIONS:
        raise ValueError(f"max_unions must be between 1 and {MAX_UNIONS}")

    sql_statements: list[str] = []
    remaining = factor

    input_table = exp.Table(this=input_table_name, db=schema_name)
    output_table = exp.Table(this=output_table_name, db=schema_name)

    while remaining > 0:
        batch_size: int = min(remaining, max_unions)

        selects: list[Select] = [
            exp.select("*").from_(input_table.copy()) for _ in range(batch_size)
        ]

        query: Query = selects[0]
        for next_select in selects[1:]:
            query = query.union(next_select, distinct=False)

        insert = exp.Insert(
            expression=query,
            into=output_table.copy(),
        )

        sql_statements.append(insert.sql(pretty=True))
        remaining -= batch_size

    return sql_statements


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
