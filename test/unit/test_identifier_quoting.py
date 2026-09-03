from functools import partial

import pytest
from sqlglot import (
    Dialects,
    exp,
    parse_one,
)

from exasol.pytest_benchmark import (
    exponential_row_data_producer,
    exponential_row_sql_data_generator,
    linear_row_data_producer,
    linear_row_sql_data_generator,
)


def target_and_source(sql_statement):
    tree = parse_one(sql_statement, dialect=Dialects.EXASOL)
    source = next(tree.find_all(exp.Select)).args["from_"].this
    return (
        tree.this.sql(dialect=Dialects.EXASOL),
        source.sql(dialect=Dialects.EXASOL),
    )


def linear_statement(schema_name, table_name):
    return linear_row_sql_data_generator(
        schema_name=schema_name,
        output_table_name=table_name,
        input_table_name="source",
        factor=1,
    )[0]


@pytest.mark.parametrize(
    "schema_name,table_name,expected",
    [
        ("bench", "target", '"bench"."target"'),
        ("BENCH", "TARGET", '"BENCH"."TARGET"'),
        ("bench", "my target", '"bench"."my target"'),
        ("bench", "table", '"bench"."table"'),
    ],
)
def test_identifiers_are_quoted_and_used_as_given(schema_name, table_name, expected):
    """Verifies identifiers are always rendered quoted and keep the exact name they
    were passed, including a name which would need quoting to be legal SQL."""
    target, _ = target_and_source(linear_statement(schema_name, table_name))
    assert target == expected


@pytest.mark.parametrize(
    "schema_name,table_name",
    [
        ('"bench"', '"target"'),
        ('"bench"', "target"),
        ("bench", '"target"'),
    ],
)
def test_enclosing_double_quotes_are_stripped(schema_name, table_name):
    """Verifies a name passed with enclosing double quotes means the same as the bare
    name, so both spellings generate identical SQL."""
    assert linear_statement(schema_name, table_name) == linear_statement(
        "bench", "target"
    )


def test_exponential_generator_quotes_identifiers():
    """Verifies both the target and the source table are quoted, in the seed insert
    as well as in the doubling inserts."""
    sql_statements = exponential_row_sql_data_generator(
        schema_name="bench",
        output_table_name="target",
        input_table_name="source",
        exponent=1,
    )

    assert target_and_source(sql_statements[0]) == (
        '"bench"."target"',
        '"bench"."source"',
    )
    assert target_and_source(sql_statements[1]) == (
        '"bench"."target"',
        '"bench"."target"',
    )


@pytest.mark.parametrize(
    "table_name,expected_name",
    [
        ('target"; DROP TABLE victim; --', 'target"; DROP TABLE victim; --'),
        ('"; DROP TABLE victim; --"', "; DROP TABLE victim; --"),
        ('"a"; DROP TABLE x; --"', 'a"; DROP TABLE x; --'),
        ("target; DROP TABLE victim", "target; DROP TABLE victim"),
        ("a.b", "a.b"),
        ('"', '"'),
    ],
)
def test_names_cannot_break_out_of_the_identifier(table_name, expected_name):
    """Verifies a name is escaped into one quoted identifier, so neither an embedded
    quote nor one exposed by stripping the enclosing quotes can add SQL."""
    tree = parse_one(linear_statement("bench", table_name), dialect=Dialects.EXASOL)

    assert isinstance(tree, exp.Insert)
    assert [table.name for table in tree.find_all(exp.Table)] == [
        expected_name,
        "source",
    ]


@pytest.mark.parametrize(
    "producer",
    [
        partial(linear_row_data_producer, factor=1),
        exponential_row_data_producer,
    ],
    ids=["linear", "exponential"],
)
def test_producers_reject_an_empty_name_before_executing(producer):
    """Verifies the producers validate while generating, so nothing is executed when
    a name is unusable."""

    def fail(sql_statement):
        raise AssertionError(f"No SQL statement expected, got: {sql_statement}")

    with pytest.raises(ValueError, match="must not be empty"):
        producer(
            query_func=fail,
            schema_name="bench",
            output_table_name="",
            input_table_name="source",
        )
