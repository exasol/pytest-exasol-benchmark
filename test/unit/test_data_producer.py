import pytest

from exasol.pytest_benchmark import (
    exponential_row_data_producer,
    exponential_row_sql_data_generator,
    linear_row_data_producer,
    linear_row_sql_data_generator,
)

SCHEMA_NAME = "test_schema"
OUTPUT_TABLE_NAME = "test_output_table"
INPUT_TABLE_NAME = "test_input_table"


@pytest.mark.parametrize(
    "factor,max_unions,expected_statement_count",
    [
        (3, 100, 1),
        (150, 100, 2),
        (5, 2, 3),
    ],
)
def test_linear_row_data_producer_executes_generated_statements_in_order(
    recording_query_func, factor, max_unions, expected_statement_count
):
    """Verifies the producer executes the linear generator's statements unchanged,
    in the generated order, and preserves their ``max_unions`` batching."""
    expected_statements = linear_row_sql_data_generator(
        schema_name=SCHEMA_NAME,
        output_table_name=OUTPUT_TABLE_NAME,
        input_table_name=INPUT_TABLE_NAME,
        factor=factor,
        max_unions=max_unions,
    )
    assert len(expected_statements) == expected_statement_count

    executed_statements = linear_row_data_producer(
        recording_query_func,
        schema_name=SCHEMA_NAME,
        output_table_name=OUTPUT_TABLE_NAME,
        input_table_name=INPUT_TABLE_NAME,
        factor=factor,
        max_unions=max_unions,
    )

    assert recording_query_func.calls == expected_statements
    assert executed_statements == recording_query_func.calls


@pytest.mark.parametrize("exponent,expected_statement_count", [(1, 2), (3, 4)])
def test_exponential_row_data_producer_executes_generated_statements_in_order(
    recording_query_func, exponent, expected_statement_count
):
    """Verifies the producer executes the exponential generator's statements
    unchanged and in order: a seed insert followed by one doubling per exponent."""
    expected_statements = exponential_row_sql_data_generator(
        schema_name=SCHEMA_NAME,
        output_table_name=OUTPUT_TABLE_NAME,
        input_table_name=INPUT_TABLE_NAME,
        exponent=exponent,
    )
    assert len(expected_statements) == expected_statement_count

    executed_statements = exponential_row_data_producer(
        recording_query_func,
        schema_name=SCHEMA_NAME,
        output_table_name=OUTPUT_TABLE_NAME,
        input_table_name=INPUT_TABLE_NAME,
        exponent=exponent,
    )

    assert recording_query_func.calls == expected_statements
    assert executed_statements == recording_query_func.calls


def test_exponential_row_data_producer_uses_default_exponent(recording_query_func):
    """Verifies omitting ``exponent`` executes the same statements as the
    generator's own default."""
    exponential_row_data_producer(
        recording_query_func,
        schema_name=SCHEMA_NAME,
        output_table_name=OUTPUT_TABLE_NAME,
        input_table_name=INPUT_TABLE_NAME,
    )

    assert recording_query_func.calls == exponential_row_sql_data_generator(
        schema_name=SCHEMA_NAME,
        output_table_name=OUTPUT_TABLE_NAME,
        input_table_name=INPUT_TABLE_NAME,
        exponent=1,
    )


@pytest.mark.parametrize(
    "factor,max_unions,expected_message",
    [
        (0, 100, "factor must be greater than 0"),
        (3, 0, "max_unions must be between 1 and 100"),
        (3, 101, "max_unions must be between 1 and 100"),
    ],
)
def test_linear_row_data_producer_rejects_invalid_input_without_executing(
    recording_query_func, factor, max_unions, expected_message
):
    """Verifies the linear generator's validation errors propagate unchanged and
    that nothing is executed when validation fails."""
    with pytest.raises(ValueError, match=expected_message):
        linear_row_data_producer(
            recording_query_func,
            schema_name=SCHEMA_NAME,
            output_table_name=OUTPUT_TABLE_NAME,
            input_table_name=INPUT_TABLE_NAME,
            factor=factor,
            max_unions=max_unions,
        )

    assert recording_query_func.calls == []


def test_exponential_row_data_producer_rejects_invalid_input_without_executing(
    recording_query_func,
):
    """Verifies an invalid ``exponent`` propagates the generator's error and that
    nothing is executed."""
    with pytest.raises(ValueError, match="exponent must be greater than or equal to 1"):
        exponential_row_data_producer(
            recording_query_func,
            schema_name=SCHEMA_NAME,
            output_table_name=OUTPUT_TABLE_NAME,
            input_table_name=INPUT_TABLE_NAME,
            exponent=0,
        )

    assert recording_query_func.calls == []
