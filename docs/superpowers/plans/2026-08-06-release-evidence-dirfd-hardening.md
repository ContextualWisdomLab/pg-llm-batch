# Descriptor-Bound Release Manifest Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development or superpowers:executing-plans and
> preserve strict red-green-refactor evidence.

**Goal:** Eliminate the check-then-use parent-path race in release manifest
creation by anchoring directory traversal, temporary-file creation, atomic
replacement, and cleanup to held directory descriptors.

**Architecture:** `write_release_manifest()` serializes first, opens the absolute
root or current directory, and traverses every parent component with `dir_fd`,
`O_DIRECTORY`, and `O_NOFOLLOW`. It creates and atomically renames the manifest
only by names relative to the final held descriptor, fails closed when secure
primitives are unavailable, and preserves the existing bounded canonical payload
and stale-temporary contract.

**Tech Stack:** Python 3.10-3.14, POSIX `openat()`/`renameat()` semantics through
`os.open(..., dir_fd=...)` and
`os.rename(..., src_dir_fd=..., dst_dir_fd=...)`, pytest, GitHub Actions.

## Global constraints

- The current replacement is PR #145, created from protected commit
  `00ed6aabb82c1754f8b14fa85929cac56f68402b`; protected `main` remains the
  integration authority and must be independently resolved again before merge.
- Do not write to superseded predecessor PR #55/#56 branches or transfer their
  checks, reviews, or generated-merge evidence to PR #145.
- Require `os.open`, `os.mkdir`, `os.stat`, `os.unlink`, and `os.rename`
  descriptor-relative support, no-follow `os.stat`, `O_DIRECTORY`, and
  `O_NOFOLLOW`; fail closed otherwise.
- Reject empty, `.`, `..`, and parent-traversal destination components.
- Keep manifest content canonical, bounded, secret-free, and unchanged.
- Request mode `0600` for the temporary file and `0700` for newly created
  evidence directories.
- Never remove a pre-existing temporary entry; remove only the temporary entry
  created by the current invocation after a later failure.
- Synchronize manifest bytes before descriptor-relative atomic rename and the
  final parent directory afterward.
- Maintain 100% production statement, branch, and public-docstring coverage.
- Do not add a workflow credential, OIDC permission, package permission,
  attestation permission, version bump, tag, or release authority.

---

### Task 1: Prove the parent-swap race and fail-closed capability contract

**Files:**
- Add: `tests/test_release_evidence_dirfd.py`

- [x] Add a deterministic parent-swap regression that renames the opened
  evidence directory and replaces its former pathname with a symlink immediately
  before temporary-file creation.
- [x] Require bytes to remain in the originally opened directory and the symlink
  target to remain untouched.
- [x] Add RED contracts for unavailable descriptor/no-follow capabilities,
  parent traversal, cleanup after atomic-rename failure, and file plus
  parent-directory synchronization.
- [x] Record historical RED head
  `7507b19ea218588d1428a0b8d190991f7a7a15cb`, CI run `31068060494`, and failing
  job `92509956104`. This is development provenance only and does not transfer
  to the replacement PR.

### Task 2: Implement descriptor-relative manifest creation

**Files:**
- Modify: `pg_llm_batch/release_evidence.py`
- Modify: `tests/test_release_evidence_dirfd.py`

- [x] Add a secure capability predicate for descriptor-relative open, directory
  creation, no-follow status inspection, unlink, and rename plus `O_DIRECTORY`
  and `O_NOFOLLOW`.
- [x] Traverse or create every parent relative to held descriptors, closing the
  predecessor descriptor only after the next directory opens successfully.
- [x] Require the final destination to be absent or regular without following a
  link.
- [x] Create the owned temporary with
  `O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW` and requested mode `0600` relative
  to the final parent descriptor.
- [x] Write canonical UTF-8, flush, synchronize the file, perform
  descriptor-relative `os.rename()`, and synchronize the final parent directory.
- [x] Clean only the owned temporary on later failure and close every descriptor.
- [x] Add bounded deterministic tests for all success, cleanup, capability, and
  operating-system failure branches.
- [x] Record historical implementation GREEN head
  `4784df03bea6a4f400c8d5cea1da28ac92dee9b5`, CI run `31068618852`, and Release
  Acceptance run `31068618818`. Those predecessor results are provenance only;
  the current replacement must regenerate exact-head evidence.

### Task 3: Make the operator and acquisition contract authoritative

**Files:**
- Modify: `docs/adr/0003-reproducible-release-evidence.md`
- Modify: `docs/doctoring/reproducible-release-evidence.md`
- Modify: `CHANGELOG.md`
- Add: `tests/test_release_evidence_dirfd_documentation.py`
- Modify: `docs/superpowers/specs/2026-08-06-release-evidence-dirfd-hardening-design.md`
- Modify: this plan

- [x] Add documentation contract tests for descriptor-relative traversal,
  `O_DIRECTORY`, `O_NOFOLLOW`, descriptor-relative `os.rename()`, both `fsync()`
  boundaries, owned-temporary cleanup, unsupported-platform refusal, rollback,
  post-return limits, and primary APA 7 references.
- [x] Record historical documentation RED head
  `260730404b0c8d34725feb2bcbaa57ba3ef980a8`, CI run `31068700294`, and failing
  job `92511916337`; it remains provenance, not replacement acceptance.
- [x] Update ADR, doctoring, changelog, design, and plan with the implemented
  contract, CWE-367, Python 3.14 `os`, and POSIX.1-2024 `openat()`/`renameat()`
  evidence.
- [ ] Run exact-head documentation, release-evidence, full CI, security, central
  required workflows, and Release Acceptance after the final replacement commit.
- [ ] Apply every valid exact-head review finding test-first and rerun all gates.

### Task 4: Verify the current replacement and finish PR #145

**Files:**
- Verify all tracked files on `feat/release-evidence-current-main`.

- [ ] Confirm the final exact head and independently resolved protected-main SHA.
- [ ] Confirm the current GitHub-generated test-merge commit identity.
- [ ] Confirm complete CI, security, central required workflows, and Release
  Acceptance success on the final exact head; do not reuse predecessor results.
- [ ] Confirm zero unresolved valid review threads and classify automated feedback
  as valid, stale, duplicate, incorrect, rate-limited, infrastructure-only, or
  superseded.
- [ ] Keep PR #145 metadata aligned with exact replacement evidence and current
  protected-main integration state.
- [ ] Request or consume current exact-head automated review through the existing
  governed paths without creating a competing reviewer workflow.
- [ ] Keep the PR draft and unmerged while any current exact-head gate or review
  thread is unresolved. When all live gates are satisfied, mark Ready and merge
  only the unchanged exact head under repository policy.

The current dependency order for this slice is protected `main` -> PR #145.
Old `.github#790 -> #53 -> #55 -> #56` ordering is historical and must not be
used as current merge authority.

## Final verification commands

```bash
uv run pytest -q
uv run ruff check .
uv run coverage run --branch -m pytest
uv run coverage report --fail-under=100
uv build
```

GitHub exact-head CI, central required workflows, security scans, and Release
Acceptance are authoritative for the replacement branch. Generated coverage
databases, build products, caches, and local evidence artifacts must remain
ignored and untracked.
