# Commercial CI and Hourly Maintenance Design

## Context

`pg-llm-batch` already receives organization-level security and review workflows, but it did not own a deterministic repository-local test/build pipeline or a repository-scoped hourly maintenance heartbeat. That left two buyer-visible risks: compatibility regressions could reach review before fast feedback existed, and approved or repairable pull requests could remain idle until another repository event occurred.

## Approaches considered

1. **Rely only on organization-required workflows.** This minimizes repository files, but it couples basic package verification to a shared queue and does not provide a repository-owned compatibility matrix.
2. **Copy the central repair and merge implementation into this repository.** This gives local control but creates governance drift and duplicates privileged automation.
3. **Add local deterministic CI and call central reusable maintenance workflows.** This keeps package verification close to the code while retaining one hardened implementation of privileged PR repair and merge behavior. This is the selected approach.

## Architecture

### Repository-local CI

`.github/workflows/ci.yml` runs on pull requests, pushes to `main`, and manual dispatch. It provides three independently visible gates:

- unit tests on Python 3.10, 3.12, and 3.14;
- compilation, Ruff, 100% docstring coverage, 100% line coverage, lock freshness, and source-independent wheel/sdist construction;
- Docker Compose validation plus builds of the component and PostgreSQL images.

All third-party actions are pinned to immutable commit SHAs. The workflow default token is read-only.

### Hourly maintenance heartbeat

`.github/workflows/hourly-maintenance.yml` runs at minute 17 of every hour and can also be dispatched manually. It calls the organization-owned PR review-fix scheduler and then the PR review-merge scheduler. Write permissions are granted only to the reusable-workflow job that needs them.

The reusable workflow references are pinned to a reviewed central commit rather than a mutable branch reference. `.github/dependabot.yml` tracks the GitHub Actions ecosystem weekly so pinned actions and reusable workflows can be refreshed by normal reviewed pull requests.

The caller does not reimplement review, autofix, branch update, or merge logic. The central `.github` repository remains the source of truth.

## Data flow

1. A PR or dependency update enters the repository.
2. Local CI proves compatibility, coverage, documentation, package construction, and container construction.
3. The hourly repair call dispatches bounded autofix for actionable feedback.
4. The hourly merge call refreshes reviews, updates stale branches, enables auto-merge, or directly merges an eligible current head.
5. Dependabot proposes reviewed updates when pinned workflow/action revisions move.
6. PR synchronization and central workflow-completion events can still trigger faster processing between hourly heartbeats.

## Failure handling

- CI jobs fail independently, preserving the concrete failed surface.
- The maintenance workflow uses `always()` before merge reevaluation, so a temporary autofix-dispatch failure does not suppress queue inspection.
- Concurrency cancels an older repository maintenance run rather than allowing overlapping privileged queue mutations.
- The central workflows retain their own stale-review, current-head, and required-check safeguards.
- Package construction uses `uv build --no-sources`, proving the distribution does not depend on workspace-only source overrides.

## Security and governance

- External actions and reusable workflows use immutable SHAs.
- The default workflow token is read-only.
- Privileged permissions are scoped per reusable-workflow call.
- Organization secrets are inherited only by the trusted central workflows.
- GitHub Actions dependencies are maintained through Dependabot rather than mutable references.
- Direct AI-generated writes to `main` are outside this design; all product changes remain pull-request based and pass the same review and CI gates.

## Validation

`tests/test_workflow_contracts.py` verifies the schedule, central workflow calls, merge behavior inputs, immutable action/workflow references, Dependabot coverage, supported Python versions, source-independent package build, container builds, and the 100% coverage/docstring thresholds. The contract is intentionally standard-library only so it runs in every supported Python environment.
