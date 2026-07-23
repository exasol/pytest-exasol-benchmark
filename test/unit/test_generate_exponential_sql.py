import pytest
from sqlglot import (
    Dialects,
    exp,
    parse_one,
)

from exasol.pytest_benchmark import exponential_row_sql_data_generator


@pytest.mark.parametrize("exponent", [1, 3])
def test_exponential_row_sql_data_generator(exponent):
    sql_statements = exponential_row_sql_data_generator(
        schema_name="test_schema",
        output_table_name="test_output_table",
        input_table_name="test_input_table",
        exponent=exponent,
    )

    assert len(sql_statements) == exponent + 1

    source_tables = []
    for statement in sql_statements:
        tree = parse_one(statement, dialect=Dialects.EXASOL)

        assert isinstance(tree, exp.Insert)
        assert len(list(tree.find_all(exp.Select))) == 1

        source_table = tree.expression.args["from_"].this.name
        source_tables.append(source_table)

    assert source_tables == ["test_input_table", *["test_output_table"] * exponent]


def test_exponential_row_sql_data_generator_rejects_invalid_exponent():
    with pytest.raises(ValueError, match="exponent must be greater than or equal to 1"):
        exponential_row_sql_data_generator(
            schema_name="test_schema",
            output_table_name="test_output_table",
            input_table_name="test_input_table",
            exponent=0,
        )
