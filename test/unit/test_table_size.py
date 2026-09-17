from datetime import datetime
from decimal import Decimal

import pytest
from sqlglot import (
    Dialects,
    exp,
    parse_one,
)

from exasol.pytest_benchmark import (
    TableSize,
    get_table_size,
    get_table_size_sql,
)

LAST_COMMIT_STRING = "2026-08-21 12:18:20.543"
LAST_COMMIT = datetime(2026, 8, 21, 12, 18, 20, 543000)


def size_row(
    row_count=3,
    raw_bytes=2048,
    mem_bytes=1024,
    last_commit=LAST_COMMIT_STRING,
):
    return [row_count, raw_bytes, mem_bytes, last_commit]


def parsed_statement(schema_name="BENCH", table_name="TARGET"):
    return parse_one(
        get_table_size_sql(schema_name=schema_name, table_name=table_name),
        dialect=Dialects.EXASOL,
    )


def test_sql_selects_the_size_columns_in_order():
    """Verifies the generated statement selects the four size columns in the order
    the inspector reads them."""
    selected = [
        projection.sql(dialect=Dialects.EXASOL)
        for projection in parsed_statement().expressions
    ]
    assert selected == [
        "T.TABLE_ROW_COUNT",
        "S.RAW_OBJECT_SIZE",
        "S.MEM_OBJECT_SIZE",
        "S.LAST_COMMIT",
    ]


def test_sql_joins_the_system_tables_through_the_object_id():
    """Verifies both system tables are queried and joined by the table's object ID,
    rather than by name."""
    statement = parsed_statement()
    tables = {
        table.sql(dialect=Dialects.EXASOL) for table in statement.find_all(exp.Table)
    }
    join = statement.args["joins"][0]
    assert tables == {"SYS.EXA_ALL_TABLES AS T", "SYS.EXA_ALL_OBJECT_SIZES AS S"}
    assert join.args["on"].sql(dialect=Dialects.EXASOL) == (
        "S.OBJECT_ID = T.TABLE_OBJECT_ID"
    )


@pytest.mark.parametrize(
    "schema_name,table_name,expected",
    [
        ("BENCH", "TARGET", "'BENCH' AND T.TABLE_NAME = 'TARGET'"),
        ("bench", "target", "'bench' AND T.TABLE_NAME = 'target'"),
        ('"BENCH"', '"TARGET"', "'BENCH' AND T.TABLE_NAME = 'TARGET'"),
        ("my schema", "my table", "'my schema' AND T.TABLE_NAME = 'my table'"),
        ("o'brien", "target", "'o''brien' AND T.TABLE_NAME = 'target'"),
    ],
)
def test_sql_compares_names_as_string_literals(schema_name, table_name, expected):
    """Verifies the names are rendered as string literals, used exactly as given
    apart from stripped enclosing double quotes, with single quotes escaped."""
    where = parsed_statement(schema_name, table_name).args["where"]
    assert where.this.sql(dialect=Dialects.EXASOL) == f"T.TABLE_SCHEMA = {expected}"


@pytest.mark.parametrize("schema_name,table_name", [("", "TARGET"), ("BENCH", "")])
def test_sql_rejects_empty_names(schema_name, table_name):
    """Verifies an empty name is rejected instead of generating a statement which
    can never match a table."""
    with pytest.raises(ValueError, match="must not be empty"):
        get_table_size_sql(schema_name=schema_name, table_name=table_name)


@pytest.mark.parametrize("schema_name,table_name", [("", "TARGET"), ("BENCH", "")])
def test_get_table_size_rejects_empty_names(
    make_recording_query_func, schema_name, table_name
):
    """Verifies the inspector rejects an empty name before executing anything."""
    query_func = make_recording_query_func([size_row()])

    with pytest.raises(ValueError, match="must not be empty"):
        get_table_size(query_func, schema_name=schema_name, table_name=table_name)

    assert query_func.calls == []


def test_get_table_size_executes_the_generated_statement(make_recording_query_func):
    """Verifies the inspector executes exactly the generated statement, once."""
    query_func = make_recording_query_func([size_row()])

    get_table_size(query_func, schema_name="BENCH", table_name="TARGET")

    assert query_func.calls == [
        get_table_size_sql(schema_name="BENCH", table_name="TARGET")
    ]


def test_get_table_size_returns_the_reported_size(make_recording_query_func):
    """Verifies the row of the query result is mapped onto ``TableSize``."""
    query_func = make_recording_query_func([size_row()])

    assert get_table_size(query_func, "BENCH", "TARGET") == TableSize(
        row_count=3, raw_bytes=2048, mem_bytes=1024, last_commit=LAST_COMMIT
    )


@pytest.mark.parametrize(
    "row_count,raw_bytes,mem_bytes",
    [
        (3, 2048, 1024),
        (Decimal("3"), Decimal("2048"), Decimal("1024")),
        ("3", "2048", "1024"),
        (3.0, 2048.0, 1024.0),
    ],
)
def test_get_table_size_accepts_the_numeric_types_exasol_returns(
    make_recording_query_func, row_count, raw_bytes, mem_bytes
):
    """Verifies whole numbers are accepted as ``int``, ``Decimal``, ``float`` and
    string, since the numeric type depends on the driver's fetch mapping."""
    query_func = make_recording_query_func(
        [size_row(row_count=row_count, raw_bytes=raw_bytes, mem_bytes=mem_bytes)]
    )

    size = get_table_size(query_func, "BENCH", "TARGET")

    assert (size.row_count, size.raw_bytes, size.mem_bytes) == (3, 2048, 1024)


@pytest.mark.parametrize(
    "last_commit", [LAST_COMMIT_STRING, "2026-08-21T12:18:20.543", LAST_COMMIT]
)
def test_get_table_size_accepts_timestamps_and_strings(
    make_recording_query_func, last_commit
):
    """Verifies the last-commit timestamp is accepted both as ``datetime`` and as the
    ISO 8601 string the driver returns by default."""
    query_func = make_recording_query_func([size_row(last_commit=last_commit)])

    assert get_table_size(query_func, "BENCH", "TARGET").last_commit == LAST_COMMIT


def test_get_table_size_accepts_a_row_of_any_sequence_type(make_recording_query_func):
    """Verifies a row is read positionally, so tuples work as well as lists."""
    query_func = make_recording_query_func(iter([tuple(size_row())]))

    assert get_table_size(query_func, "BENCH", "TARGET").row_count == 3


@pytest.mark.parametrize(
    "result,expected_message",
    [
        ([], "was not found or is not accessible"),
        ([size_row(), size_row()], "returned 2 rows instead of one"),
        ([[3, 2048, 1024]], "returned 3 columns instead of the expected 4"),
        ([{"TABLE_ROW_COUNT": 3}], "returned a row of type dict"),
        ([None], "which is not iterable"),
        ([size_row(row_count=None)], "reported no row count"),
        ([size_row(raw_bytes=None)], "reported no raw size"),
        ([size_row(mem_bytes=None)], "reported no memory size"),
        ([size_row(last_commit=None)], "reported no last-commit timestamp"),
        ([size_row(row_count="many")], "which is not a number"),
        ([size_row(row_count=True)], "which is not a number"),
        ([size_row(row_count=Decimal("NaN"))], "which is not a number"),
        ([size_row(raw_bytes=Decimal("Infinity"))], "which is not a number"),
        ([size_row(mem_bytes=float("nan"))], "which is not a number"),
        ([size_row(raw_bytes=2048.5)], "not a whole number"),
        ([size_row(last_commit="21.08.2026")], "not an ISO 8601 timestamp"),
        ([size_row(last_commit=42)], "neither a 'datetime' nor a timestamp string"),
        (None, "has to return the query result"),
        (42, "which is not iterable"),
        ("no rows here", "has to return the query result"),
    ],
)
def test_get_table_size_fails_clearly(
    make_recording_query_func, result, expected_message
):
    """Verifies a missing table and every malformed query result fail with a
    ``ValueError`` naming the table and the problem."""
    query_func = make_recording_query_func(result)

    with pytest.raises(ValueError, match=expected_message) as error:
        get_table_size(query_func, schema_name="BENCH", table_name="TARGET")

    assert '"BENCH"."TARGET"' in str(error.value)


def test_get_table_size_names_virtual_tables_as_unsupported(
    make_recording_query_func,
):
    """Verifies the ``NULL`` row count of a virtual table points at the fact that
    virtual schemas and virtual tables are out of scope."""
    query_func = make_recording_query_func([size_row(row_count=None)])

    with pytest.raises(ValueError, match="virtual schemas and virtual tables"):
        get_table_size(query_func, "BENCH", "VIRTUAL_TARGET")
