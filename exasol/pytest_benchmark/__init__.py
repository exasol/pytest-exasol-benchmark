from contextlib import contextmanager
from importlib.metadata import version

from sqlglot import (
    Dialects,
    exp,
)

from .models import ArtifactManifest as ArtifactManifest
from .models import ComparisonReport as ComparisonReport
from .models import ComparisonResult as ComparisonResult
from .models import NormalizedCase as NormalizedCase
from .models import PlatformMetadata as PlatformMetadata
from .models import RunnerExecution as RunnerExecution
from .models import TestSetCollection as TestSetCollection

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


def _to_identifier(name: str) -> exp.Identifier:
    """
    Turn a schema or table name into a quoted SQL identifier.

    The name is used exactly as given and always rendered quoted, so `target` becomes
    `"target"` and keeps its case. Enclosing double quotes are stripped first, so
    `'"target"'` also resolves to `target`. Any double quote left in the name is
    escaped, so a name can never end the identifier and change the statement.

    Note that Exasol converts unquoted identifiers to uppercase: a table
    created by `CREATE TABLE bench.target` is called `TARGET` and has to be passed as
    such. Passing an empty name raises a `ValueError`.
    """
    if len(name) >= 2 and name.startswith('"') and name.endswith('"'):
        name = name[1:-1]
    if not name:
        raise ValueError("A schema or table name must not be empty")
    return exp.to_identifier(name, quoted=True)


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
    Therefore, the generator returns `ceil(factor / max_unions)` SQL statements.

    Returns a list of SQL statements.
    Example:
        factor=3,   max_unions=100 -> 1 SQL statement
        factor=150, max_unions=100 -> 2 SQL statements: 100 + 50
    """
    if factor < 1:
        raise ValueError("factor must be greater than 0")
    if max_unions < 1 or max_unions > MAX_UNIONS:
        raise ValueError(f"max_unions must be between 1 and {MAX_UNIONS}")

    sql_statements: list[str] = []
    remaining = factor

    input_table = exp.table_(
        table=_to_identifier(input_table_name), db=_to_identifier(schema_name)
    )
    output_table = exp.table_(
        table=_to_identifier(output_table_name), db=_to_identifier(schema_name)
    )

    while remaining > 0:
        batch_size: int = min(remaining, max_unions)

        selects: list[Select] = [
            exp.select("*").from_(input_table.copy()) for _ in range(batch_size)
        ]

        query: Query = selects[0]
        for next_select in selects[1:]:
            query = query.union(next_select, distinct=False)

        insert = exp.Insert(
            this=output_table.copy(),
            expression=query,
        )

        sql_statements.append(insert.sql(dialect=Dialects.EXASOL, pretty=True))
        remaining -= batch_size

    return sql_statements


def exponential_row_sql_data_generator(
    schema_name: str,
    output_table_name: str,
    input_table_name: str,
    exponent: int = 1,
) -> list[str]:
    """Generate SQL statements that grow ``output_table_name`` exponentially.

    The first SQL statement copies the input table to the output table.
    Each subsequent SQL statement inserts the output table into itself, doubling its
    row count. Consequently, executing all returned SQL statements produces
    ``2 ** exponent`` copies of the input table's rows.

    Therefore, the generator returns ``exponent + 1`` SQL statements: one initial copy
    followed by ``exponent`` doubling statements.
    """
    if exponent < 1:
        raise ValueError("exponent must be greater than or equal to 1")

    input_table = exp.table_(
        table=_to_identifier(input_table_name), db=_to_identifier(schema_name)
    )
    output_table = exp.table_(
        table=_to_identifier(output_table_name), db=_to_identifier(schema_name)
    )

    source_tables = [input_table, *([output_table] * exponent)]
    return [
        exp.Insert(
            this=output_table.copy(),
            expression=exp.select("*").from_(source_table.copy()),
        ).sql(dialect=Dialects.EXASOL, pretty=True)
        for source_table in source_tables
    ]


def linear_row_data_producer(
    query_func: QueryFunc,
    schema_name: str,
    output_table_name: str,
    input_table_name: str,
    factor: int,
    max_unions: int = MAX_UNIONS,
) -> list[str]:
    """
    Copy the rows of `schema_name.input_table_name` into `schema_name.output_table_name`
    `factor` times, by executing the SQL statements of
    :func:`linear_row_sql_data_generator` in the generated order.

    Returns the list of executed SQL statements.

    The output table must already exist. The generated statements are INSERTs, so
    calling this function twice adds `2 * factor` copies in total.
    """
    sql_statements = linear_row_sql_data_generator(
        schema_name=schema_name,
        output_table_name=output_table_name,
        input_table_name=input_table_name,
        factor=factor,
        max_unions=max_unions,
    )
    return _execute_statements(query_func, sql_statements)


def exponential_row_data_producer(
    query_func: QueryFunc,
    schema_name: str,
    output_table_name: str,
    input_table_name: str,
    exponent: int = 1,
) -> list[str]:
    """
    Grow `schema_name.output_table_name` to `2 ** exponent` copies of the rows of
    `schema_name.input_table_name`, by executing the SQL statements of
    :func:`exponential_row_sql_data_generator` in the generated order.

    Returns the list of executed SQL statements.

    The output table must already exist and is expected to be empty. The generated
    statements are INSERTs which double the output table in place, so calling this
    function on a non-empty output table compounds the rows already present.
    """
    sql_statements = exponential_row_sql_data_generator(
        schema_name=schema_name,
        output_table_name=output_table_name,
        input_table_name=input_table_name,
        exponent=exponent,
    )
    return _execute_statements(query_func, sql_statements)


def _execute_statements(query_func: QueryFunc, sql_statements: list[str]) -> list[str]:
    for sql_statement in sql_statements:
        logger.debug("Executing SQL statement: %s", sql_statement)
        query_func(sql_statement)
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
