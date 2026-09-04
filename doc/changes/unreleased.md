# Unreleased

## Summary

Added versioned public models for benchmark artifacts, the Git-trackable
benchmark-history layout, and comparison reports, data producer helpers which
execute the generated benchmark-data SQL, and an inspector for the size of an
existing table.

## Features

* #10: Added versioned benchmark artifact, history, and comparison models
* #11: Added data producer helpers for linear and exponential data
* #12: Added `get_table_size` and `get_table_size_sql`, which report the row count,
  the uncompressed and compressed size, and the last-commit timestamp of an existing
  table

## Bugfixes

* #11: Fixed `linear_row_sql_data_generator` generating `INSERT` statements without
  a target table
* #11: Fixed inconsistent identifier quoting in the SQL generators.  Schema and table
  names are now always rendered as quoted identifiers and used exactly as given, with
  enclosing double quotes stripped and any remaining quote escaped, so a name can no
  longer change the generated statement.  Names are no longer upper-cased, so a name
  which relied on Exasol resolving it upper-cased has to be passed uppercase now

## Refactorings

* #12: Moved the SQL identifier and literal rendering to `identifier` and the query
  result conversion to `conversion`
* #12: Made the `conversion` helpers independent of the table size query, so they can
  convert the result of any query

## Dependency Updates

### `main`

* Added dependency `pydantic:2.13.4`
