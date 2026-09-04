"""Conversion of query result rows and values into Python types."""

from collections.abc import Mapping
from datetime import datetime
from decimal import (
    Decimal,
    InvalidOperation,
)
from typing import Any


def _append_hint(message: str, null_hint: str) -> str:
    """Append `null_hint` to `message`, if the caller passed one."""
    return f"{message}. {null_hint}" if null_hint else message


def single_row(
    result: Any,
    source: str,
    expected_columns: int,
    null_hint: str = "",
) -> list[Any]:
    """
    Extract the single row of `expected_columns` columns which a query about `source`
    returned.

    `source` names what was queried in every error message and has to read as an
    object, for example ``'table "BENCH"."TARGET"'``.  `null_hint` is appended to
    the error raised for a result without rows, because only the caller knows why its
    query may have matched nothing.

    Raises a `ValueError` naming `source` if the query returned no or more than one
    row, or if the result does not have the expected shape.
    """
    if result is None or isinstance(result, (str, bytes)):
        raise ValueError(
            f"Querying {source} returned {result!r}. The 'query_func' has to "
            "return the query result, an iterable of rows"
        )
    try:
        rows = list(result)
    except TypeError as error:
        raise ValueError(
            f"Querying {source} returned {type(result).__name__}, which is not "
            "iterable. The 'query_func' has to return the query result, an iterable "
            "of rows"
        ) from error

    if not rows:
        raise ValueError(_append_hint(f"Querying {source} returned no rows", null_hint))
    if len(rows) > 1:
        raise ValueError(f"Querying {source} returned {len(rows)} rows instead of one")

    row = rows[0]
    if isinstance(row, (Mapping, str, bytes)):
        raise ValueError(
            f"Querying {source} returned a row of type {type(row).__name__}. "
            "Rows have to be sequences of column values"
        )
    try:
        values = list(row)
    except TypeError as error:
        raise ValueError(
            f"Querying {source} returned a row of type {type(row).__name__}, "
            "which is not iterable. Rows have to be sequences of column values"
        ) from error
    if len(values) != expected_columns:
        raise ValueError(
            f"Querying {source} returned {len(values)} columns instead of the "
            f"expected {expected_columns}"
        )
    return values


def to_int(value: Any, column: str, source: str, null_hint: str = "") -> int:
    """
    Convert the `column` value of a query result row about `source` to an `int`.

    `column` and `source` name the value in every error message, `null_hint` is
    appended to the error raised for a `NULL` value.
    """
    if value is None:
        raise ValueError(
            _append_hint(f"Exasol reported no {column} for {source}", null_hint)
        )
    if isinstance(value, bool):
        raise ValueError(
            f"Exasol reported the {column} of {source} as {value!r}, which is not "
            "a number"
        )
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(
            f"Exasol reported the {column} of {source} as {value!r}, which is not "
            "a number"
        ) from error
    if not number.is_finite():
        raise ValueError(
            f"Exasol reported the {column} of {source} as {value!r}, which is not "
            "a number"
        )
    if number != number.to_integral_value():
        raise ValueError(
            f"Exasol reported the {column} of {source} as {value!r}, which is not "
            "a whole number"
        )
    return int(number)


def to_datetime(value: Any, column: str, source: str, null_hint: str = "") -> datetime:
    """
    Convert the `column` value of a query result row about `source` to a `datetime`.

    `column` and `source` name the value in every error message, `null_hint` is
    appended to the error raised for a `NULL` value.
    """
    if value is None:
        raise ValueError(
            _append_hint(f"Exasol reported no {column} for {source}", null_hint)
        )
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError(
                f"Exasol reported the {column} of {source} as {value!r}, which is "
                "not an ISO 8601 timestamp. The session's 'NLS_TIMESTAMP_FORMAT' has "
                "to keep the default format"
            ) from error
    raise ValueError(
        f"Exasol reported the {column} of {source} as {value!r}, which is neither a "
        "'datetime' nor a timestamp string"
    )
