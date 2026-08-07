# Hourly Maintenance Credential Boundary Implementation Plan

> **Required workflow:** Use test-driven development and verification before
> completion. Do not add a temporary write-capable workflow.

## Goal

Migrate the `pg-llm-batch` hourly review-repair caller to the hardened central
scheduler contract while preserving the independent merge plane and binding CI
evidence to the exact pull-request source head.

## Dependency

The implementation is stacked logically on `ContextualWisdomLab/.github#782`.
The current prerequisite SHA is used only for Draft verification. Final promotion
requires the protected merge SHA from central `main` and fresh exact-head gates.

This replacement branch starts from protected `pg-llm-batch` main
`bf2cc2e140dc3ff4a56c3203f80f41bb9fed5d10`, which already contains the bounded
provider-response test-double repair from merged PR #68. The predecessor feature
branch diverged before that merge; its stale-base CI failures are not product
regressions and are not reused as success evidence.

## Task 1: Prove the current caller is unsafe

- [x] Add a focused test requiring the exact current central scheduler SHA.
- [x] Require explicit mapping of only the two established scheduler secrets.
- [x] Reject job-level GitHub-token write permissions in the review-fix job.
- [x] Reject `secrets: inherit` in the review-fix job.
- [x] Preserve the existing independent review-merge contract.
- [x] Record RED CI `31172887367` on test-only predecessor head
      `df7a51333684ee6230a92696f9180cf39bbba5f5`. Its two credential-boundary
      failures are development evidence only.

## Task 2: Implement the bounded caller migration

- [x] Pin `pr-review-fix-scheduler.yml` to current `.github#782` head
      `70fd801523893ba2c51ad9bd859b2d3c408d5839` for Draft verification.
- [x] Update `canonical_ref` to the same immutable SHA.
- [x] Remove the review-fix job permission elevation.
- [x] Replace inherited secrets with explicit scheduler secret mapping.
- [x] Keep cadence, retry floor, dispatch bound, and concurrency unchanged.
- [x] Keep the merge scheduler pin, permissions, inputs, and secret inheritance
      unchanged.
- [x] When the prerequisite advanced from the earlier reviewed head, update the
      exact-pin contract first. RED head `62fb2f2d9251586f37b30f6e24cfa18c11ddf458`
      failed CI run `31201274230` only because the caller still referenced the
      predecessor central SHA. Implementation then moved the caller and both
      governance contracts to the same current prerequisite identity.

## Task 3: Bind CI to the exact source head

- [x] Add a RED contract requiring every repository CI checkout to use
      `${{ github.event.pull_request.head.sha || github.sha }}` and immediately
      verify `git rev-parse HEAD`.
- [x] Record RED CI `31186479041`, which proved the predecessor workflow executed
      GitHub's synthetic pull-request merge ref instead of the exact source head.
- [x] Make the test topology-independent by counting checkout sites dynamically,
      so any future CI job without the same identity proof fails closed.
- [x] Update all CI checkout sites to use the exact source-head expression with
      `persist-credentials: false` and a post-checkout equality assertion.
- [x] Rebase the bounded slice onto current protected main rather than copying
      stale-base test failures forward.

## Task 4: Document the operator and trust boundary

- [x] Add ADR 0013 with GitHub primary-documentation references in APA 7 form.
- [x] Keep the existing secret names as the operator contract; no new credential
      or model-secret setup is introduced by this caller-only migration.
- [x] Record the scheduler and exact-source CI changes under `CHANGELOG.md`
      Unreleased.

## Task 5: Verify and promote

- [ ] Run focused workflow-contract tests on the exact source head.
- [ ] Run the complete non-integration suite on the exact source head.
- [ ] Require Ruff and 100% production statement/branch coverage on the exact
      source head.
- [ ] Require 100% production docstring coverage on the exact source head.
- [ ] Require lock freshness, package builds, Compose validation, and both
      container builds on the exact source head.
- [ ] Require current-head security, SAST, dependency, SBOM, and review gates.
- [ ] After central #782 merges, replace the temporary SHA with its protected
      merge SHA and rerun every gate.
- [ ] Merge only with zero unresolved valid findings and a qualifying independent
      non-author approval.

Synthetic merge runs and predecessor-branch results remain useful diagnostic or
RED evidence only. Final acceptance is tied exclusively to the exact current
source head on the exact protected base.
