import pytest
from sqlglot import (
    Dialects,
    exp,
    parse_one,
)

from exasol.pytest_benchmark import (
    MAX_UNIONS,
    linear_row_sql_data_generator,
)


@pytest.mark.parametrize(
    "factor,max_unions,sql_statements,expected_select_counts,expected_union_counts",
    [(250, 100, 3, [100, 100, 50], [99, 99, 49]), (1, 100, 1, [1], [0])],
)
def test_generate_linear_sql_batches_by_max_unions(
    factor, max_unions, sql_statements, expected_select_counts, expected_union_counts
):
    actual_sql_statements = linear_row_sql_data_generator(
        schema_name="test_schema",
        output_table_name="test_output_table",
        input_table_name="test_input_table",
        factor=factor,
        max_unions=max_unions,
    )

    assert len(actual_sql_statements) == sql_statements

    expected_select_counts = expected_select_counts
    expected_union_counts = expected_union_counts

    for stmt, expected_selects, expected_unions in zip(
        actual_sql_statements, expected_select_counts, expected_union_counts
    ):
        tree = parse_one(stmt, dialect=Dialects.EXASOL)

        assert isinstance(tree, exp.Insert)
        assert (
            tree.this.sql(dialect=Dialects.EXASOL)
            == '"test_schema"."test_output_table"'
        )
        assert len(list(tree.find_all(exp.Select))) == expected_selects
        assert len(list(tree.find_all(exp.Union))) == expected_unions


def test_linear_row_sql_data_generator_rejects_invalid_factor():
    with pytest.raises(ValueError, match="factor must be greater than 0"):
        linear_row_sql_data_generator(
            schema_name="test_schema",
            output_table_name="test_output_table",
            input_table_name="test_input_table",
            factor=0,
        )


@pytest.mark.parametrize("max_unions", [0, MAX_UNIONS + 1])
def test_linear_row_sql_data_generator_rejects_invalid_max_unions(max_unions):
    with pytest.raises(
        ValueError,
        match=rf"max_unions must be between 1 and {MAX_UNIONS}",
    ):
        linear_row_sql_data_generator(
            schema_name="test_schema",
            output_table_name="test_output_table",
            input_table_name="test_input_table",
            factor=1,
            max_unions=max_unions,
        )
