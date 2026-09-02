# Unreleased

## Summary

Added versioned public models for benchmark artifacts, the Git-trackable
benchmark-history layout, and comparison reports, plus data producer helpers which
execute the generated benchmark-data SQL.

## Features

* #10: Added versioned benchmark artifact, history, and comparison models
* #11: Added data producer helpers for linear and exponential data

## Bugfixes

* #11: Fixed `linear_row_sql_data_generator` generating `INSERT` statements without
  a target table
* #11: Fixed inconsistent identifier quoting in the SQL generators.  Schema and table
  names are now always rendered as quoted identifiers and used exactly as given, with
  enclosing double quotes stripped and any remaining quote escaped, so a name can no
  longer change the generated statement.  Names are no longer upper-cased, so a name
  which relied on Exasol resolving it upper-cased has to be passed uppercase now

## Dependency Updates

### `main`

* Added dependency `pydantic:2.13.4`
