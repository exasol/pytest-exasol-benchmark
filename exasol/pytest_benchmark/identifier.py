"""Rendering of schema and table names given by the caller into SQL."""

from sqlglot import exp


def to_identifier(name: str) -> exp.Identifier:
    """
    Turn a schema or table name into a quoted SQL identifier.

    The name is used exactly as given and always rendered quoted, so `target` becomes
    `"target"` and keeps its case. Enclosing double quotes are stripped first, so
    `'"target"'` also resolves to `target`. Any double quote left in the name is
    escaped, so a name can never end the identifier and change the statement.

    Note that Exasol converts unquoted identifiers to uppercase: a table
    created by `CREATE TABLE bench.target` is called `TARGET` and has to be passed as
    such. Passing an empty name raises a `ValueError`.
    """
    return exp.to_identifier(normalized_name(name), quoted=True)


def normalized_name(name: str) -> str:
    """
    Normalize a schema or table name as given by the caller.

    Enclosing double quotes are stripped, so `'"target"'` and `"target"` both resolve
    to `target`.  The case is kept as given.  Passing an empty name raises a
    `ValueError`.
    """
    if len(name) >= 2 and name.startswith('"') and name.endswith('"'):
        name = name[1:-1]
    if not name:
        raise ValueError("A schema or table name must not be empty")
    return name


def to_string_literal(name: str) -> exp.Literal:
    """
    Turn a schema or table name into a SQL string literal.

    The system tables hold names as string *values*, so they are compared against
    literals rather than identifiers.  The name is normalized as described in
    :func:`normalized_name` and any single quote in it is escaped, so a name can
    never end the literal and change the statement.
    """
    return exp.Literal.string(normalized_name(name))
