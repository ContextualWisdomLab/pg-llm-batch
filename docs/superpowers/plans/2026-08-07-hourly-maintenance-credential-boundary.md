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
- [ ] Record the failing normal CI run on the test-only head.

## Task 2: Implement the bounded caller migration

- [ ] Pin `pr-review-fix-scheduler.yml` to the exact prerequisite SHA.
- [ ] Update `canonical_ref` to the same immutable SHA.
- [ ] Remove the review-fix job permission elevation.
- [ ] Replace inherited secrets with explicit scheduler secret mapping.
- [ ] Keep cadence, retry floor, dispatch bound, and concurrency unchanged.
- [ ] Keep the merge scheduler pin, permissions, inputs, and secret inheritance
      unchanged.

## Task 3: Document the operator and trust boundary

- [x] Add ADR 0013 with GitHub primary-documentation references in APA 7 form.
- [ ] Update README or operator automation documentation if the final diff needs
      a caller-facing setup note.
- [ ] Record the change under `CHANGELOG.md` Unreleased.

## Task 4: Verify and promote

- [ ] Run focused workflow-contract tests.
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
