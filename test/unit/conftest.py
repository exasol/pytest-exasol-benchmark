from collections.abc import Callable

import pytest

from exasol.pytest_benchmark import QueryResult


class RecordingQueryFunc:
    """Stands in for a real ``QueryFunc`` in tests.

    Instead of executing SQL against a database, it records every statement it was
    called with in :attr:`calls`, so tests can assert which statements ran and in
    which order. ``result`` is what the call returns, for tests that need a value
    back.
    """

    def __init__(self, result: QueryResult = None) -> None:
        self.calls: list[str] = []
        self._result = result

    def __call__(self, sql_statement: str) -> QueryResult:
        self.calls.append(sql_statement)
        return self._result


@pytest.fixture
def recording_query_func() -> RecordingQueryFunc:
    return RecordingQueryFunc()


@pytest.fixture
def make_recording_query_func() -> Callable[[QueryResult], RecordingQueryFunc]:
    """Create a ``RecordingQueryFunc`` which returns ``result`` for every call.

    For tests which need a query result back, such as the table size inspector.
    """
    return RecordingQueryFunc
