"""Pytest plugin for benchmarking queries against an Exasol database."""

from contextlib import contextmanager
from importlib.metadata import version

from sqlglot import (
    Dialects,
    exp,
)

from .conversion import (
    single_row,
    to_datetime,
    to_int,
)
from .identifier import (
    normalized_name,
    to_identifier,
    to_string_literal,
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
from dataclasses import dataclass
from datetime import datetime
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

#: Number of columns the table size query selects, see `get_table_size_sql`.
TABLE_SIZE_COLUMNS: int = 4

#: Appended to the error raised when the table size query matches no table.
_TABLE_NOT_FOUND_HINT = (
    "The table was not found or is not accessible. Schema and table name are matched "
    "exactly, and Exasol stores the name of an unquoted identifier uppercase, so a "
    "table created by 'CREATE TABLE bench.target' has to be passed as schema 'BENCH' "
    "and table 'TARGET'"
)

#: Appended to the error raised when the table size query reports no value.
_VIRTUAL_TABLE_HINT = "Note that virtual schemas and virtual tables are not supported"


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
        table=to_identifier(input_table_name), db=to_identifier(schema_name)
    )
    output_table = exp.table_(
        table=to_identifier(output_table_name), db=to_identifier(schema_name)
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
        table=to_identifier(input_table_name), db=to_identifier(schema_name)
    )
    output_table = exp.table_(
        table=to_identifier(output_table_name), db=to_identifier(schema_name)
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


@dataclass(frozen=True)
class TableSize:
    """
    The size of an existing Exasol table, as reported by the system tables.

    `row_count` is the number of rows, `raw_bytes` the uncompressed and `mem_bytes`
    the compressed data volume in bytes, and `last_commit` the time of the most
    recent modification.  See :func:`get_table_size` for how the values are read.
    """

    row_count: int
    raw_bytes: int
    mem_bytes: int
    last_commit: datetime


def get_table_size_sql(schema_name: str, table_name: str) -> str:
    """
    Generate the SQL statement which reads the size of `schema_name.table_name` from
    the Exasol system tables.

    The statement joins `SYS.EXA_ALL_TABLES` and `SYS.EXA_ALL_OBJECT_SIZES` through
    the table's object ID and selects row count, uncompressed size, compressed size
    and last-commit timestamp, in that order.

    The system tables hold schema and table names as string values, so both names are
    rendered as string literals and are used exactly as given, only stripped of
    enclosing double quotes.  Note that Exasol stores the name of an unquoted
    identifier uppercase: a table created by `CREATE TABLE bench.target` has to be
    looked up as schema `BENCH` and table `TARGET`.
    """
    tables = exp.table_("EXA_ALL_TABLES", db="SYS", alias="T")
    object_sizes = exp.table_("EXA_ALL_OBJECT_SIZES", db="SYS", alias="S")
    query = (
        exp.select(
            "T.TABLE_ROW_COUNT",
            "S.RAW_OBJECT_SIZE",
            "S.MEM_OBJECT_SIZE",
            "S.LAST_COMMIT",
        )
        .from_(tables)
        .join(
            object_sizes,
            on=exp.column("OBJECT_ID", "S").eq(exp.column("TABLE_OBJECT_ID", "T")),
            join_type="inner",
        )
        .where(exp.column("TABLE_SCHEMA", "T").eq(to_string_literal(schema_name)))
        .where(exp.column("TABLE_NAME", "T").eq(to_string_literal(table_name)))
    )
    return query.sql(dialect=Dialects.EXASOL, pretty=True)


def get_table_size(
    query_func: QueryFunc, schema_name: str, table_name: str
) -> TableSize:
    """
    Read the current size of the existing table `schema_name.table_name`, by executing
    the SQL statement of :func:`get_table_size_sql` through `query_func`.

    `query_func` has to return the query result: an iterable of rows, where each row
    is a sequence of column values, as returned by `pyexasol`'s `execute`.

    Exasol reports the sizes and the last-commit timestamp as of the last `COMMIT`, so
    a table modified in an open transaction is measured as it was before.  The sizes
    of `SYS.EXA_ALL_OBJECT_SIZES` are calculated recursively, which is not free on a
    database with many objects.

    Raises a `ValueError` if the table does not exist, is not accessible, or if the
    query result does not have the expected shape.
    """
    source = f'table "{normalized_name(schema_name)}"."{normalized_name(table_name)}"'
    sql_statement = get_table_size_sql(schema_name=schema_name, table_name=table_name)
    logger.debug("Executing SQL statement: %s", sql_statement)
    row = single_row(
        query_func(sql_statement),
        source,
        expected_columns=TABLE_SIZE_COLUMNS,
        null_hint=_TABLE_NOT_FOUND_HINT,
    )
    return TableSize(
        row_count=to_int(row[0], "row count", source, _VIRTUAL_TABLE_HINT),
        raw_bytes=to_int(row[1], "raw size", source, _VIRTUAL_TABLE_HINT),
        mem_bytes=to_int(row[2], "memory size", source, _VIRTUAL_TABLE_HINT),
        last_commit=to_datetime(
            row[3], "last-commit timestamp", source, _VIRTUAL_TABLE_HINT
        ),
    )


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
