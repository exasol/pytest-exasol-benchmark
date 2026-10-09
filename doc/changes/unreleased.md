# Unreleased

## Summary

Added versioned public models for benchmark artifacts, the Git-trackable
benchmark-history layout, and comparison reports, data producer helpers which
execute the generated benchmark-data SQL, an inspector for the size of an
existing table, the `pytest-exasol-benchmark` executable with its `package`
command and skeletons of its `compare` and `store` commands, storing runner
artifacts as the benchmark history, normalizing pytest-benchmark JSON for
comparisons, collecting downloaded runner artifacts for comparison with
the history, and comparing them with the history.

## Features

* #10: Added versioned benchmark artifact, history, and comparison models
* #11: Added data producer helpers for linear and exponential data
* #12: Added `get_table_size` and `get_table_size_sql`, which report the row count,
  the uncompressed and compressed size, and the last-commit timestamp of an existing
  table
* #13: Added the `pytest-exasol-benchmark` executable with the command skeletons
  `package`, `compare`, and `store`, which validate their arguments
* #14: Implemented the `package` command
* #15: Added `store_history`, which stores runner artifacts as the benchmark history
* #16: Added `normalize_execution` and `normalize_benchmark`, which normalize
  pytest-benchmark JSON into cases keyed by `fullname`
* #17: Added `collect_candidates`, which collects downloaded runner artifacts into one
  validated candidate collection per test set and comparison target
* #18: Added `compare_with_history`, `compare_collections`, and `aggregate_collection`,
  which compare runner benchmark with the checked-out history

## Bugfixes

* #14: Fixed the query cache staying disabled after a failing benchmark
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
* #31: Made the integration tests share a single database per test session instead
  of starting one per test
* #15: `load_history` now ignores entries whose names start with a dot, reports all
  duplicate runner executions at once, validates each execution like a packaged
  artifact, and rejects execution directories without a manifest, symbolic links,
  and the history of a running or interrupted store

## Dependency Updates

### `main`

* Added dependency `click:8.5.0`
* Added dependency `pydantic:2.13.4`
