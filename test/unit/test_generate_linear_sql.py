import pytest
from sqlglot import expressions as exp
from sqlglot import parse_one

from exasol.pytest_benchmark import linear_row_sql_data_generator


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
        tree = parse_one(stmt)

        assert isinstance(tree, exp.Insert)
        assert len(list(tree.find_all(exp.Select))) == expected_selects
        assert len(list(tree.find_all(exp.Union))) == expected_unions
