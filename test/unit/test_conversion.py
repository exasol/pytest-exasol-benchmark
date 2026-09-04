from datetime import datetime

import pytest

from exasol.pytest_benchmark.conversion import (
    single_row,
    to_datetime,
    to_int,
)

SOURCE = 'view "BENCH"."STATS"'


def test_single_row_reads_any_column_count():
    """Verifies the extraction is not tied to a specific query: it accepts whatever
    number of columns the caller asks for."""
    assert single_row([("cold", 17)], SOURCE, expected_columns=2) == ["cold", 17]


def test_to_int_reads_any_column():
    """Verifies the conversion is not tied to a specific column."""
    assert to_int("17", "hit count", SOURCE) == 17


def test_to_datetime_reads_any_column():
    """Verifies the conversion is not tied to a specific column."""
    assert to_datetime("2026-08-21 12:18:20.543", "measured at", SOURCE) == datetime(
        2026, 8, 21, 12, 18, 20, 543000
    )


@pytest.mark.parametrize(
    "call,expected_message",
    [
        (
            lambda hint: single_row([], SOURCE, 2, null_hint=hint),
            f"Querying {SOURCE} returned no rows",
        ),
        (
            lambda hint: to_int(None, "hit count", SOURCE, hint),
            f"Exasol reported no hit count for {SOURCE}",
        ),
        (
            lambda hint: to_datetime(None, "measurement timestamp", SOURCE, hint),
            f"Exasol reported no measurement timestamp for {SOURCE}",
        ),
    ],
)
def test_a_missing_value_is_reported_without_a_hint(call, expected_message):
    """Verifies a caller which knows no hint gets the bare message, without a
    dangling separator."""
    with pytest.raises(ValueError) as error:
        call("")

    assert str(error.value) == expected_message


@pytest.mark.parametrize(
    "call,expected_message",
    [
        (
            lambda hint: single_row([], SOURCE, 2, null_hint=hint),
            f"Querying {SOURCE} returned no rows. Run the benchmark first",
        ),
        (
            lambda hint: to_int(None, "hit count", SOURCE, hint),
            f"Exasol reported no hit count for {SOURCE}. Run the benchmark first",
        ),
        (
            lambda hint: to_datetime(None, "measurement timestamp", SOURCE, hint),
            f"Exasol reported no measurement timestamp for {SOURCE}. "
            "Run the benchmark first",
        ),
    ],
)
def test_a_missing_value_is_reported_with_the_callers_hint(call, expected_message):
    """Verifies the caller's hint explains a missing value, so the helpers carry no
    knowledge of the query they convert the result of."""
    with pytest.raises(ValueError) as error:
        call("Run the benchmark first")

    assert str(error.value) == expected_message


def test_a_hint_is_not_added_to_an_unrelated_failure():
    """Verifies the hint only explains a missing value: a value of the wrong type is
    not a missing one."""
    with pytest.raises(ValueError) as error:
        to_int("many", "hit count", SOURCE, "Run the benchmark first")

    assert "Run the benchmark first" not in str(error.value)
