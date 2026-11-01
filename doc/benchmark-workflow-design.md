# Benchmark workflow and reusable Nox sessions

## Status

Design proposal.

This document describes how benchmark pull requests should be checked, how an
accepted baseline is written back to the same pull request, and how the
workflow logic is exposed through reusable Nox sessions in the released
`pytest-exasol-benchmark` package.

The package provides reusable workflow templates and Nox sessions that render
them. Repository-specific configuration remains explicit in the consuming
repository; the generator does not discover or silently modify project
configuration.

## Goals

- Run benchmark matrices and package one artifact per runner.
- Compare candidate artifacts with the checked-in `benchmark-history`.
- Allow an intentional performance regression to become mergeable after manual
  approval.
- Store the accepted baseline on the source pull-request branch, so the pull
  request contains both the code change and its new baseline.
- Reject results benchmarked against a stale pull-request base.
- Preserve provenance even when the pull request is squash-merged and its
  original commit becomes unreachable.
- Make the benchmark operations reusable by other repositories through the
  released Python package.
- Keep generated workflows deterministic, reviewable, and easy to customize.

## Non-goals

- Starting Exasol databases or provisioning runner infrastructure.
- Deciding whether a measured regression is acceptable automatically.
- Making fork pull requests write to repository branches.

## Current gaps

The Python APIs for artifacts, history, normalization, and comparison exist,
and this design assumes the `compare` and `store` CLI commands are complete and
released. Workflows should call those CLIs directly rather than adding Nox
wrappers around them.

The current `package` command also does not accept arbitrary manifest
attributes. Provenance metadata must be added either through a new package CLI
option or by a Python-level packaging API.

## Proposed architecture

```text
Nox workflow-generation session
        |
        v
generated GitHub Actions workflow
        |
        v
GitHub Actions workflow
        |
        +--> pytest CLI
        +--> pytest-exasol-benchmark package CLI
        +--> artifact and history APIs
```

The workflow generator owns the stable workflow structure:

- benchmark matrix job structure;
- artifact transport;
- comparison and baseline-update job dependencies;
- permissions and protected-environment hooks;
- provenance and base-freshness wiring.

The generated workflow still owns GitHub concerns at runtime:

- matrix definition;
- artifact upload/download;
- permissions;
- protected environments and reviewers;
- branch updates;
- pull-request checks.

The package CLI and APIs own benchmark concerns:

- invoking the project’s benchmark command;
- validating and packaging JSON;
- comparing artifacts;
- storing accepted history;
- producing machine-readable results.

Nox owns only concerns where no suitable CLI exists:

- rendering and checking workflow templates;
- checking that the benchmark base is still current;
- assembling GitHub provenance metadata before calling the package CLI.

The consuming repository owns:

- benchmark matrix values;
- benchmark command and test paths;
- test-set and comparison-target identifiers;
- Exasol setup steps or reusable setup actions;
- protected environment names;
- optional repository-specific workflow steps.

## Workflow lifecycle

### 1. Benchmark matrix

Each matrix job should:

1. check out the pull-request revision;
2. establish the Exasol connection and benchmark data;
3. run pytest with an explicit JSON destination;
4. package the JSON with a unique runner execution ID;
5. upload the resulting artifact directory.

The benchmark job must not package or upload results after a failed pytest
run. A failed benchmark test must not become a partial candidate.

The output path should be explicit and temporary, for example:

```bash
pytest --benchmark-json="$RUNNER_TEMP/benchmark/output.json"
poetry run nox -s benchmark:package -- \
  --benchmark-json "$RUNNER_TEMP/benchmark/output.json" \
  --runner-execution-id "$RUNNER_ID"
```

### 2. Candidate comparison

A comparison job downloads all runner artifacts side-by-side. It must not use
`merge-multiple: true`, because `collect_candidates()` expects one artifact
per subdirectory.

The comparison job records three outcomes:

- comparison succeeded with no regressions;
- comparison succeeded with one or more regressions;
- comparison could not be performed because the input or baseline is invalid.

The first two outcomes are successful technical checks. The third fails the
required check.

This separation is essential: an intentional regression must not fail the
comparison job before a reviewer can approve it.

### 3. Base freshness check

The benchmark result records the PR base SHA from:

```text
github.event.pull_request.base.sha
```

Before comparison is accepted, a reusable session queries the current base SHA
and fails if it differs from the recorded value. This forces a benchmark rerun
when the target branch advances.

GitHub’s native “require branches to be up to date before merging” setting
should also be enabled. The custom check protects benchmark provenance; the
native setting protects the merge result.

### 4. Manual acceptance and baseline update

The baseline-update job is a required protected-environment job. It:

1. waits for configured reviewers;
2. checks out the source branch of the pull request;
3. stores the complete candidate matrix as `benchmark-history`;
4. commits the history update to that same branch;
5. pushes the branch update.

The job must never push directly to the protected default branch.

After the baseline commit, the pull-request workflow runs again. The final PR
therefore contains the source change and its accepted baseline, and the
post-update comparison validates that combination.

For fork pull requests, the normal pull-request token cannot safely update the
fork branch. Forks require a separate trusted `workflow_dispatch` or
`workflow_run` promotion path, with explicit repository-owner approval.

## Provenance model

`source_revision` remains the exact commit used for the benchmark execution,
but it must not be the only provenance field. A squash merge can make that
commit unreachable.

The manifest should gain a structured provenance area, initially represented
as `attributes.provenance` if schema compatibility is required:

```json
{
  "source_revision": "pr-head-sha",
  "attributes": {
    "provenance": {
      "repository": "owner/repository",
      "ref": "feature/query-optimization",
      "commit_sha": "pr-head-sha",
      "tree_sha": "source-tree-sha",
      "base_sha": "target-branch-sha",
      "base_tree_sha": "target-tree-sha",
      "pull_request_number": 123,
      "pull_request_url": "https://github.com/owner/repository/pull/123",
      "workflow_run_id": "456789",
      "workflow_run_attempt": 1,
      "benchmark_config_sha256": "...",
      "dependency_lock_sha256": "..."
    }
  }
}
```

The source tree hash should exclude `benchmark-history`; otherwise updating the
baseline changes the apparent source identity. The accepted history should be
identified separately, for example with a `benchmark_history_tree_sha`.

The final squash-merge SHA is not available when the PR benchmark runs. If it
is required for audit purposes, a post-merge job may add it later as
`accepted_merge_sha`. The original execution SHA must remain unchanged.

## Reusable released-package Nox API

### Workflow generation

The released package should expose workflow-generation sessions, for example:

```bash
poetry run nox -s benchmark:workflow -- \
  --output .github/workflows/benchmark.yml \
  --config benchmark-workflow.yml
```

The session renders a versioned template shipped in the Python package. It
must not generate arbitrary Python or execute the benchmark. It should:

- validate the configuration before writing anything;
- render deterministically;
- write atomically;
- refuse to overwrite a modified generated file unless `--force` is supplied;
- include the package/template version in a generated-file header;
- support a check mode that exits nonzero when the checked-in workflow is stale;
- validate the resulting YAML and required job/action invariants.

The generated workflow should contain clearly marked extension points for
repository-specific setup, for example an `exasol_setup` step block supplied
by configuration. Templates must not embed credentials or database secrets.

The consumer repository’s Nox file remains small and owns only configuration
for the Nox-only operations:

```python
from exasol.pytest_benchmark.nox import benchmark_sessions

benchmark_sessions(
    workflow_config="benchmark-workflow.yml",
    workflow_output=".github/workflows/benchmark.yml",
)
```

The checked-in generated workflow is an auditable build artifact. Pull
requests update it by running the generator and reviewing the resulting YAML.

### Packaging

The released package should expose a Nox integration module, for example:

```python
from exasol.pytest_benchmark.nox import benchmark_sessions

benchmark_sessions()
```

The consumer repository’s `noxfile.py` remains small and owns only project
configuration:

```python
from exasol.pytest_benchmark.nox import benchmark_sessions

benchmark_sessions(
    pytest_command=("pytest", "tests/benchmarks"),
    test_set_id="tpch-sf10",
    comparison_target="onprem-standard",
    history_root="benchmark-history",
)
```

The exact registration API may instead expose individual functions, but the
consumer must not copy the implementation into its repository. Existing CLIs
remain the preferred interface for benchmark execution, packaging, comparison,
and storage.

### Required sessions

The initial reusable sessions should be:

| Session | Responsibility | Writes repository state? |
|---|---|---:|
| `benchmark:workflow` | Render the reusable GitHub Actions workflow from configuration | Yes, generated workflow file |
| `benchmark:workflow-check` | Verify the checked-in generated workflow is current and valid | No |
| `benchmark:base-current` | Verify the recorded PR base SHA when no equivalent CLI is available | No |
| `benchmark:provenance` | Generate/validate GitHub provenance input when no equivalent CLI is available | No |

The following operations use the released command-line interfaces directly and
should not receive redundant Nox wrappers:

- `pytest` for benchmark execution;
- `pytest-exasol-benchmark package`;
- `pytest-exasol-benchmark compare`;
- `pytest-exasol-benchmark store`.

Sessions should be composable. A workflow can call a single session for a
simple repository or call the sessions separately when database setup and
artifact transport require custom steps.

### Session interface

Sessions should accept explicit command-line options and environment variables,
not repository-specific hard-coded paths. At minimum:

- benchmark command or pytest arguments;
- benchmark JSON path;
- artifact output path;
- artifacts input directory;
- test-set ID;
- comparison target;
- runner execution ID;
- source and base revision metadata;
- history root;
- threshold;
- optional provenance JSON path.

Environment variables are appropriate for GitHub metadata, but every value
must also have a deterministic CLI equivalent for local use and testing.

### Nox dependency strategy

Nox is needed when importing the session module, but it is not needed by the
runtime artifact/comparison APIs. The package should therefore provide an
optional dependency extra, for example:

```toml
[project.optional-dependencies]
nox = ["nox>=2024.4,<2027"]
```

Consumer repositories use:

```bash
pip install "pytest-exasol-benchmark[nox]"
```

The core package must remain importable without Nox installed. The Nox module
should either be imported explicitly only by `noxfile.py` or provide a clear
error explaining that the extra is required.

## Task breakdown

Tasks are intentionally sized so each produces a reviewable change.

### A. Add provenance support

1. Add a provenance model or an `attributes.provenance` contract.
   - Validate JSON-safe values.
   - Document required versus optional fields.

2. Add provenance input to packaging.
   - Prefer `--provenance-json FILE` for extensibility.
   - Preserve byte-identical benchmark JSON.
   - Keep `source_revision` for compatibility.

3. Add helpers for Git provenance.
   - PR head SHA and base SHA.
   - source tree SHA.
   - source tree SHA excluding `benchmark-history`.
   - benchmark configuration and lockfile hashes.

4. Add tests for squash-merge-safe provenance and history exclusion.

### B. Implement reusable Nox sessions

5. Add an optional Nox dependency and package module.
   - Keep core imports independent of Nox.
   - Define the supported public session-registration API.

6. Implement `benchmark:base-current` and `benchmark:provenance` only for
   functionality not exposed by the package CLI.
   - Distinguish stale-base failure from invalid input.
   - Emit machine-readable output for workflow conditions.
   - Never push or create pull requests.

7. Add a small consumer-fixture repository in tests.
    - Install the released-style package.
    - Import sessions from a minimal `noxfile.py`.
    - Verify the sessions are discoverable and reusable outside this source
      tree.

8. Add packaged workflow templates and configuration models.
    - Define the supported configuration schema.
    - Include templates in the wheel and source distribution.
    - Validate identifiers, paths, environment names, and action versions.

9. Implement `benchmark:workflow` and `benchmark:workflow-check`.
    - Deterministic rendering.
    - Atomic writes and modified-file protection.
    - YAML parsing and invariant checks.
    - Golden-file tests for the generated workflows.

### C. Build the GitHub workflow

10. Add the generated benchmark matrix workflow.
    - Explicit `--benchmark-json` path.
    - One uploaded artifact per runner.
    - No packaging after failed pytest.

11. Add candidate download and comparison using the package CLI.
    - Preserve one artifact per subdirectory.
    - Upload comparison reports.
    - Keep valid regressions distinguishable from invalid comparison failures.

12. Add base freshness validation using the Nox-only session where no CLI is
    available.
    - Compare recorded `base_sha` with the current PR base SHA.
    - Make the check required for merging.

13. Add the protected same-branch baseline update job using the package CLI.
    - Restrict the write path to same-repository PRs.
    - Require the `benchmark-baseline-approval` environment.
    - Commit and push `benchmark-history` to the PR source branch.

14. Add fork-promotion documentation and a separate trusted path.
    - Do not grant write permissions to untrusted fork code.
    - Use an owner-triggered dispatch or workflow-run promotion.

### D. Documentation and release quality

15. Document the consumer `noxfile.py` integration, generator configuration,
    and all session options.

16. Document GitHub environment reviewers, required checks, branch protection,
    and merge queue behavior.

17. Add package-build tests proving the Nox module, templates, and metadata are included in
    the wheel/sdist.

18. Add a release note and migration guidance for repositories currently using
    the direct CLI commands.

## Suggested implementation order

```text
A1-A4  provenance
   |
C5-C9 reusable Nox-only sessions and workflow generation
   |
C10-C14 GitHub workflow
   |
D15-D18 documentation and release validation
```

The workflow should not be enabled until A, B, and C are complete. Otherwise
the repository would have a workflow that depends on unimplemented provenance,
generator, or session APIs. The compare and store CLIs are assumed available
from the start.

## Acceptance criteria

- A repository can install `pytest-exasol-benchmark[nox]`, import the public
  Nox-only session API from its own `noxfile.py`, and run the sessions without
  copying implementation code.
- A repository can render its benchmark workflow from a versioned package
  template and detect stale generated output in CI.
- A PR benchmark stores the exact PR head, target base, source tree, and
  workflow provenance.
- A target-branch advance invalidates the benchmark result.
- A valid regression can be manually approved and makes the source PR
  mergeable.
- The approved baseline is committed to that same source PR branch.
- No workflow job pushes directly to the protected default branch.
- Fork PRs cannot use untrusted code to write repository contents.
- Squash merging does not destroy the ability to identify the benchmarked PR,
  source snapshot, comparison base, and workflow run.
