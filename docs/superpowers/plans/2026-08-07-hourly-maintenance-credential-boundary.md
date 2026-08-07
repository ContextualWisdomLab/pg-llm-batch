# Hourly Maintenance Credential Boundary Implementation Plan

> **Required workflow:** Use test-driven development and verification before
> completion. Do not add a temporary write-capable workflow.

## Goal

Migrate the `pg-llm-batch` hourly review-repair caller to the hardened central
scheduler contract while preserving the independent merge plane.

## Dependency

The implementation is stacked logically on `ContextualWisdomLab/.github#782`.
The current prerequisite SHA is used only for Draft verification. Final promotion
requires the protected merge SHA from central `main` and fresh exact-head gates.

## Task 1: Prove the current caller is unsafe

- [x] Add a focused test requiring the exact current central scheduler SHA.
- [x] Require explicit mapping of only the two established scheduler secrets.
- [x] Reject job-level GitHub-token write permissions in the review-fix job.
- [x] Reject `secrets: inherit` in the review-fix job.
- [x] Preserve the existing independent review-merge contract.
- [x] Record RED CI `31172887367` on test-only head
      `df7a51333684ee6230a92696f9180cf39bbba5f5`. Its two credential-boundary
      failures are the intended RED evidence; the other failures came from a
      stale synthetic merge base and were fixed independently on protected
      `main`, so they are not reused as feature evidence.

## Task 2: Implement the bounded caller migration

- [x] Pin `pr-review-fix-scheduler.yml` to current `.github#782` head
      `b921e26854f1b0fd367c76a32af6db966374bcef` for Draft verification.
- [x] Update `canonical_ref` to the same immutable SHA.
- [x] Remove the review-fix job permission elevation.
- [x] Replace inherited secrets with explicit scheduler secret mapping.
- [x] Keep cadence, retry floor, dispatch bound, and concurrency unchanged.
- [x] Keep the merge scheduler pin, permissions, inputs, and secret inheritance
      unchanged.

## Task 3: Document the operator and trust boundary

- [x] Add ADR 0013 with GitHub primary-documentation references in APA 7 form.
- [x] Keep the existing secret names as the operator contract; no new credential
      or model-secret setup is introduced by this caller-only migration.
- [x] Record the change under `CHANGELOG.md` Unreleased.

## Task 4: Verify and promote

- [ ] Run focused workflow-contract tests on the implementation head.
- [ ] Run the complete non-integration suite.
- [ ] Require Ruff and 100% production statement/branch coverage.
- [ ] Require 100% production docstring coverage.
- [ ] Require lock freshness, package builds, Compose validation, and both
      container builds.
- [ ] Require current-head security, SAST, dependency, SBOM, and review gates.
- [ ] After central #782 merges, replace the temporary SHA with its protected
      merge SHA and rerun every gate.
- [ ] Merge only with zero unresolved valid findings and a qualifying independent
      non-author approval.
