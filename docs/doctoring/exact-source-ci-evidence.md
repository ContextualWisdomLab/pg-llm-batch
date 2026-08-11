# Exact-source CI evidence boundary

## Decision

Pull-request CI must execute the exact pull-request source head, not GitHub's
synthetic pull-request merge ref, whenever the evidence is later used to claim
that a specific source head passed repository-owned tests, coverage, packaging,
or container gates.

Every `actions/checkout` site in `.github/workflows/ci.yml` therefore binds
`ref` to `${{ github.event.pull_request.head.sha || github.sha }}` and is
immediately followed by an equality check between `git rev-parse HEAD` and that
same event-derived identity. `persist-credentials: false` remains mandatory.

The fallback to `github.sha` preserves push and manual workflow behavior. On a
`pull_request` event, the event payload's `pull_request.head.sha` is the source
branch commit under review.

## Root cause

For an open mergeable pull request, GitHub sets the `pull_request` event's
`GITHUB_REF` to `refs/pull/<number>/merge` and `GITHUB_SHA` to the synthetic
merge commit. `actions/checkout` follows that ref by default. The former
workflow therefore produced integration evidence for a GitHub-generated merge
commit while repository policy discussed acceptance of an exact source head.
Those are different evidence identities.

This mismatch was originally repaired inside the broader hourly-maintenance
hardening work, but that work has an independent cross-repository scheduler
dependency. Exact-source CI identity is a repository-local evidence contract and
must not be serialized behind that unrelated dependency.

## Test-first evidence

Draft PR #88 began with test-only source head
`c3055a6d0ffe071fb24f2f08484ddb6d302ae16c`. CI run `31303723366` failed the
new permanent contract on Python 3.10 at the intended boundary: the workflow had
three checkout sites and zero exact-source `ref` bindings. The observed result
was `1 failed, 349 passed, 3 deselected`.

Implementation head `019086b2fb1e0dd7a1e9431a63213609386aed32`
added the same source identity and immediate verification to all three checkout
sites. In CI run `31303766114`, the `Checkout` and `Verify exact source head`
steps succeeded in the Python 3.10, 3.12, 3.14, coverage/docstring/package, and
container jobs; the Python and quality gates also completed successfully before
this record was written.

No scheduler credentials, maintenance cadence, reviewer identity, model
credential, branch protection, package behavior, database behavior, or release
authority is changed by this slice.

## Evidence classification

- Exact-source CI proves repository-owned validation ran on the source commit
  named by the pull request.
- It does not replace branch protection, independent review, security checks, or
  merge-policy validation.
- A later source-head change invalidates earlier source-head evidence.
- A synthetic merge run may still be useful integration evidence, but it is not
  interchangeable with exact-source evidence.
- Pending, cancelled, skipped, absent, failed, stale-head, status-only, or
  predecessor-head evidence remains non-passing.

## Rollback

Rollback consists of reverting the workflow and contract-test commits. Doing so
would intentionally restore synthetic-merge checkout semantics and must also
remove any claim that ordinary PR CI is exact-source evidence. No data migration
or persistent runtime state is involved.

## References

GitHub. (n.d.). *Events that trigger workflows*. GitHub Docs. Retrieved August
9, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

GitHub. (n.d.). *Contexts reference*. GitHub Docs. Retrieved August 9, 2026,
from
https://docs.github.com/en/actions/reference/workflows-and-actions/contexts
