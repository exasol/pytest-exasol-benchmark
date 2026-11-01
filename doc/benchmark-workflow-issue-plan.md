# GitHub issue plan: Nox-driven benchmark workflow integration

This document is the issue-writing plan for the benchmark workflow design. It
describes the overview issue and its child tickets; it is not an implementation
plan and does not itself create, update, or close GitHub issues.

## Overview issue

Suggested title:

```text
Nox-driven benchmark workflow integration
```

Suggested label: `feature`.

Suggested body:

```markdown
## Goal

Integrate benchmark execution, artifact comparison, provenance, approval, and
same-branch baseline promotion through a reusable package contract.

The consumer controls benchmark execution and project-specific setup. Existing
package CLIs remain the interface for packaging, comparison, and history
storage. Nox provides only the operations that do not already have a suitable
CLI, plus deterministic generation of the reusable orchestrator workflows.
The generator configuration describes orchestrator behavior only; benchmark
matrices, commands, IDs, and setup remain in consumer-owned workflows.

## Design references

- `doc/benchmark-workflow-design.md`
- `doc/github-benchmark-workflow-sketches.yml`
- `doc/benchmark-workflow-config.example.json`

## Workflow boundaries

- `benchmark-run.yml`: consumer-owned benchmark matrix and artifact creation.
- `benchmark-parent.yml`: consumer-owned workflow composition and configuration.
- `benchmark-orchestrator.yml`: generated Poetry/PTB orchestration workflow.
- `benchmark-workflow-check.yml`: generated freshness-check workflow.

## Artifact contract

The orchestrator consumes only packaged runner artifacts:

```text
artifacts/<runner-name>/manifest.json
artifacts/<runner-name>/benchmark.json
```

Artifacts remain separated by runner directory after download.

## CLI and Nox boundary

Workflows call these commands directly:

- `pytest-exasol-benchmark package`;
- `pytest-exasol-benchmark compare`;
- `pytest-exasol-benchmark store`.

Nox sessions cover:

- `benchmark:check-base`;
- `benchmark:provenance`;
- `benchmark:commit-baseline`;
- `benchmark:generate-workflow`;
- `benchmark:generate-example`.

## Acceptance criteria

- Consumer benchmark execution remains project-controlled.
- Valid regressions remain reviewable and do not become technical comparison failures.
- Invalid artifacts, invalid history, and stale base metadata fail clearly.
- Baseline commits are limited to the pull-request source branch and history paths.
- Generated workflows are deterministic and checked for freshness in CI.
- Provenance remains useful after squash merging.
- The generated example validates without Exasol, Docker, credentials, or network access.
```

## Child tickets

All child tickets should use the `feature` label and remain unassigned.

### 1. Add benchmark provenance model and packaging support

Scope:

- Define and validate `attributes.provenance`.
- Add provenance input to artifact packaging while preserving `source_revision`.
- Calculate source-tree, benchmark-configuration, and dependency-lock hashes.
- Exclude `benchmark-history` from source identity.
- Preserve byte-identical benchmark JSON.

Acceptance criteria:

- Provenance is JSON-safe and validated before packaging.
- Squash-merge-safe source and workflow metadata are retained.
- Tests cover history exclusion, hash determinism, and packaging compatibility.

Dependencies: none.

### 2. Add reusable Nox registration and session infrastructure

Scope:

- Add the optional Nox dependency.
- Add the public `benchmark_sessions()` registration helper.
- Define `workflow_config` and `workflow_output_dir` as workflow-generation
  defaults only.
- Keep core artifact and CLI imports independent of Nox.
- Add discovery coverage from a minimal consumer `noxfile.py`.

Acceptance criteria:

- A consumer can import and register the package sessions without copying implementation code.
- The helper does not accept benchmark commands, matrices, IDs, runner mappings,
  or project-specific setup.
- Core package functionality remains importable without Nox.
- Required session names are discoverable.

Dependencies: none.

### 3. Implement `benchmark:check-base`

Scope:

- Accept explicit expected base SHA, repository, PR number, and token inputs.
- Support GitHub environment fallbacks.
- Query the current pull-request base through a Python client/helper.
- Fail with both expected and current SHAs when stale.

Acceptance criteria:

- Current-base checks succeed.
- Stale-base checks fail deterministically.
- Local tests do not require GitHub credentials or network access.

Dependencies: Nox infrastructure.

### 4. Implement `benchmark:provenance`

Scope:

- Generate provenance from explicit local or GitHub metadata.
- Write and validate deterministic JSON.
- Provide source, base, workflow, configuration, and dependency metadata.

Acceptance criteria:

- Generated output is accepted by packaging.
- Explicit CLI arguments work without GitHub credentials.
- Invalid or incomplete metadata fails clearly.

Dependencies: provenance model and Nox infrastructure.

### 5. Implement `benchmark:commit-baseline`

Scope:

- Verify that only the configured history paths changed.
- Reject default-branch and unrelated-working-tree updates.
- Configure the GitHub Actions identity.
- Commit only when history changes exist.
- Push explicitly to the pull-request source branch.

Acceptance criteria:

- No protected default branch can be targeted.
- Unrelated changes are never committed.
- Git behavior is covered with mocked command tests.

Dependencies: Nox infrastructure and history storage CLI behavior (#19).

### 6. Implement `benchmark:generate-workflow`

Scope:

- Accept explicit orchestrator configuration and output directory arguments.
- Include and validate the orchestrator-only example configuration from
  `doc/benchmark-workflow-config.example.json`.
- Generate `benchmark-orchestrator.yml` and `benchmark-workflow-check.yml` from
  orchestrator-only configuration.
- Render deterministic Poetry/PTB workflows.
- Support atomic writes, modified-file protection, `--force`, and `--check`.
- Validate YAML and required job/action invariants.
- Do not define or infer benchmark commands, matrices, IDs, or project setup.

Acceptance criteria:

- Repeated generation produces byte-identical files.
- Modified generated files are protected unless forced.
- Check mode detects stale or invalid generated files.
- The generated workflows use direct package CLIs where available.

Dependencies: Nox infrastructure, base/provenance/commit sessions.

### 7. Implement `benchmark:generate-example`

Scope:

- Generate the complete four-workflow example consumer.
- Include a local deterministic benchmark and explicit benchmark JSON output.
- Include consumer Nox registration and project configuration.
- Validate generated files without Exasol, Docker, credentials, or network access.

Acceptance criteria:

- The expected file set is generated deterministically.
- Artifact directories preserve one runner per directory.
- Generated YAML and workflow invariants validate successfully.

Dependencies: Nox infrastructure and workflow generator.

### 8. Add consumer `benchmark-run.yml`

Scope:

- Keep benchmark matrix and project-specific setup consumer-owned.
- Run pytest with an explicit `--benchmark-json` path.
- Generate provenance, package successful results, and upload one artifact per runner.

Acceptance criteria:

- Failed benchmark runs cannot upload candidate artifacts.
- The workflow does not contain comparison, storage, or Git promotion logic.
- The artifact contract is preserved.

Dependencies: provenance/packaging support and workflow generator.

### 9. Add consumer `benchmark-parent.yml`

Scope:

- Invoke the consumer benchmark-run workflow.
- Pass matrix and project-specific configuration.
- Forward the artifact run ID and recorded base SHA to the orchestrator.

Acceptance criteria:

- The parent owns composition only.
- It does not inspect artifacts or implement benchmark operations.
- It invokes the generated orchestrator as a reusable workflow.

Dependencies: benchmark-run workflow and workflow generator.

### 10. Add generated `benchmark-orchestrator.yml`

Scope:

- Use the PTB Python environment action and Poetry.
- Run base freshness validation.
- Download artifacts without merging runner directories.
- Invoke direct `compare` and `store` CLIs.
- Upload comparison reports.
- Apply protected approval and invoke guarded baseline commit.

Acceptance criteria:

- No inline `jq`, `gh api`, comparison exit-code handling, `git commit`, or `git push` exists.
- Valid regressions remain eligible for approval.
- Invalid comparison inputs fail the required check.
- Same-repository and fork safety boundaries are explicit.

Dependencies: #19, Nox sessions, benchmark-run and parent workflows.

### 11. Add generated `benchmark-workflow-check.yml`

Scope:

- Trigger on workflow configuration, generator, and generated-file changes.
- Set up the project with PTB and Poetry.
- Run `benchmark:generate-workflow --check`.
- Fail when either generated workflow is stale.

Acceptance criteria:

- The checker validates both generated workflow files.
- Stale generated output fails CI.
- The checker itself is generated and included in freshness validation.

Dependencies: workflow generator.

### 12. Complete documentation, packaging, and release integration

Scope:

- Document consumer Nox registration and workflow configuration.
- Document approval environments, branch protection, and fork promotion.
- Add wheel/sdist inclusion tests for Nox modules and workflow assets.
- Add release notes and migration guidance.

Acceptance criteria:

- Consumer integration is copy-ready.
- Package-build tests prove required assets are distributed.
- Existing direct CLI consumers have migration guidance.

Dependencies: implementation of the preceding workstreams.

## Existing issue references

- Issue #19 remains the dependency for comparison and history-storage CLI behavior and should not be duplicated.
- Issue #20 is superseded by this design because it prohibits workflow changes. The issue plan should call for closing it as not planned with an explanatory comment.
