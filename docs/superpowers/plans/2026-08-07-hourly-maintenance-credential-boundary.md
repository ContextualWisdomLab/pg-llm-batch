# Hourly Maintenance Credential Boundary Implementation Plan

> **Required workflow:** Use test-driven development and verification before
> completion. Do not add a temporary write-capable workflow.

## Goal

Migrate the `pg-llm-batch` hourly review-repair caller to the hardened central
scheduler contract while preserving the independent merge plane, binding CI
evidence to the exact pull-request source head, ensuring a later hourly trigger
cannot cancel an active RCA or bounded repair, and retaining a realistic
short-lived mutation-credential path without granting repository writes to the
workflow-generated token.

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
- [x] Reject repository write permissions for the workflow-generated token in
      the review-fix job.
- [x] Reject `secrets: inherit` in the review-fix job.
- [x] Preserve the existing independent review-merge contract.
- [x] Record RED CI `31172887367` on test-only predecessor head
      `df7a51333684ee6230a92696f9180cf39bbba5f5`. Its two credential-boundary
      failures are development evidence only.

## Task 2: Implement the bounded caller migration

- [x] Pin `pr-review-fix-scheduler.yml` and `canonical_ref` to the exact current
      `.github#782` candidate `afd33b5d09f331f2b73913c1d4b312be9296a449`
      for Draft verification.
- [x] Remove all repository write elevation from the review-fix caller.
- [x] Replace inherited secrets with explicit scheduler secret mapping.
- [x] Keep the one-hour cadence, one-hour retry floor, and one-dispatch repair
      bound.
- [x] Keep the merge scheduler pin, permissions, inputs, and secret inheritance
      unchanged.
- [x] When the prerequisite advanced from earlier reviewed heads, update the
      exact-pin test before implementation and regenerate exact-head evidence.
      RED heads `62fb2f2d9251586f37b30f6e24cfa18c11ddf458`,
      `07bb189b3f554195eba48bcc0124aca50a6f5faf`, and
      `76c9e86cbcd6ba5885bf28a3a96037b0a56d27d5` each captured a deterministic
      predecessor-pin mismatch before the workflow moved.
- [x] Treat the cancelled predecessor run `31234208124` only as superseded
      diagnostic history; it is not passing or executed RED evidence.

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

## Task 4: Preserve RCA and scope writer-lease recovery

- [x] Add a failing contract requiring queued single-flight maintenance instead
      of cancellation of the active run.
- [x] Record exact-head RED CI `31257187170` on
      `6ef1dd64f2f088f83b9bd975870e4c17c5ecc07d`: one intended scheduler
      assertion failed on Python 3.10/3.12/3.14 and coverage because the workflow
      still used `cancel-in-progress: true`.
- [x] Change the concurrency group to `cancel-in-progress: false` plus
      `queue: max`, retaining one running maintenance workflow while allowing
      later hourly triggers to wait rather than discard active work.
- [x] Record implementation GREEN CI `31257294919`, Security Scan
      `31257294934`, and SAST Semgrep `31257294909` on exact head
      `d689750fa4df3fb17b1d82f590da4a52e2754218`.
- [x] Add a documentation contract requiring root-cause analysis, candidate
      remedies, feasibility evaluation, execution, and branch-scoped lease
      recovery.
- [x] Record exact-head documentation RED CI `31257371090` on
      `90748552a9a389daac3b4198cd165a69fbfad790`: the intended single contract
      failed because ADR 0013 did not yet define that recovery behavior.
- [x] Define actual lease conflict as movement of the same `pg-llm-batch` target
      branch, PR, or blob, while treating read-only dependency movement as scoped
      evidence invalidation and reconciliation rather than a repository-wide
      stop.
- [x] Record ADR-contract GREEN CI `31257451896`, Security Scan
      `31257451894`, and SAST Semgrep `31257451900` on exact head
      `07b6535b0f965b2be8ef4343332ad873df935387`.

## Task 5: Restore realistic short-lived mutation authority

- [x] Inspect the central candidate and prove that its preferred mutation path
      exchanges a GitHub OIDC assertion for a short-lived OpenCode GitHub App
      token, with the two explicit secrets as fallbacks.
- [x] Add a RED caller contract requiring exactly `contents: read` and
      `id-token: write`, while still rejecting every repository write permission,
      `secrets: inherit`, `COPILOT_GITHUB_TOKEN`, and caller-side model secrets.
- [x] Record exact-head RED CI `31258604528` on
      `63c0def47f48167cb82b89c3e4c0f300b2319f23`: the intended permission
      assertion failed because the review-fix caller could not request OIDC.
- [x] Add only the two required caller permissions at implementation head
      `46e181b48a74465cfb370c71ef80c4b1240aff70`.
- [x] Replace a newline-sensitive test assertion with an exact structural set
      comparison at `0fcf4419c75747712bb7fd0d1c1f16ea8e046d63`; CI
      `31258740858`, Security Scan `31258740833`, and SAST Semgrep
      `31258740855` then succeeded on that exact source head.
- [x] Add a RED documentation contract at
      `94b4ee3c553879485dadd20518f6d0d34f3f350b`; CI `31258829737` failed the
      intended missing OIDC feasibility statement and is retained only as RED
      evidence.
- [x] Document that `id-token: write` authorizes OIDC token issuance rather than
      repository mutation, that the app token is short-lived, and that repair
      fails closed only when both OIDC exchange and explicit fallbacks are
      unavailable.
- [x] Record documentation GREEN CI `31258889981`, Security Scan
      `31258889951`, and SAST Semgrep `31258889957` on exact head
      `9b172f8e271c116386dd4181ccf8b74353d492f1`.

## Task 6: Document the operator and trust boundary

- [x] Add ADR 0013 with GitHub primary-documentation references in APA 7 form.
- [x] Keep the existing secret names as fallback operator contracts; no new
      long-lived credential or model-secret setup is introduced.
- [x] Document the short-lived OIDC exchange, exact caller permissions, and
      fail-closed availability boundary.
- [x] Document the RCA → remedy → feasibility → execution sequence and the
      distinction between same-target writer conflicts and read-only dependency
      drift.
- [x] Record the scheduler, exact-source CI, queued recovery, and OIDC changes
      under `CHANGELOG.md` Unreleased.

## Task 7: Verify and promote

- [ ] Run focused workflow-contract tests on the exact final source head.
- [ ] Run the complete non-integration suite on the exact final source head.
- [ ] Require Ruff and 100% production statement/branch coverage on the exact
      final source head.
- [ ] Require 100% production docstring coverage on the exact final source head.
- [ ] Require lock freshness, package builds, Compose validation, and both
      container builds on the exact final source head.
- [ ] Require current-head security, SAST, dependency, SBOM, and review gates.
- [ ] After central #782 merges, replace the temporary SHA with its protected
      merge SHA and rerun every gate.
- [ ] Merge only with zero unresolved valid findings and a qualifying independent
      non-author approval.

Synthetic merge runs and predecessor-branch results remain useful diagnostic or
RED evidence only. Final acceptance is tied exclusively to the exact current
source head on the exact protected base.
