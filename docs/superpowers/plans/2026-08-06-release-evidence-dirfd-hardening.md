# Descriptor-Bound Release Manifest Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the check-then-use parent-path race in release manifest creation by anchoring directory traversal, temporary-file creation, atomic replacement, and cleanup to held directory descriptors.

**Architecture:** `write_release_manifest()` will serialize first, open the absolute root or current directory, and traverse every parent component with `dir_fd`, `O_DIRECTORY`, and `O_NOFOLLOW`. It will create and replace the manifest only by names relative to the final held descriptor, fail closed when the secure primitives are unavailable, and preserve the existing bounded canonical payload and stale-temporary contract.

**Tech Stack:** Python 3.10-3.14, POSIX `openat()`/`renameat()` semantics through `os.open(..., dir_fd=...)` and `os.replace(..., src_dir_fd=..., dst_dir_fd=...)`, pytest, GitHub Actions.

## Global Constraints

- Base the branch on PR #55 exact head `3660bb9edd6351a9c02d9507f08ed647ddbf0d3a` and do not write to PR #53 or #55 branches.
- Require `os.open`, `os.mkdir`, `os.stat`, `os.unlink`, and `os.replace` descriptor-relative support plus `O_DIRECTORY` and `O_NOFOLLOW`; fail closed otherwise.
- Reject empty, `.`, `..`, and parent-traversal destination components.
- Keep manifest content canonical, bounded, secret-free, and unchanged.
- Preserve mode `0600` for the temporary file and use mode `0700` for newly created evidence directories.
- Never remove a pre-existing temporary entry; remove only the temporary entry created by the current invocation after a later failure.
- Maintain 100% production statement, branch, and public-docstring coverage.
- Do not add a workflow, credential, OIDC permission, package permission, attestation permission, version bump, tag, or release.

---

### Task 1: Prove the parent-swap race and fail-closed capability contract

**Files:**
- Modify: `tests/test_release_evidence.py`

**Interfaces:**
- Consumes: `write_release_manifest(manifest: Mapping[str, Any], output_path: str | Path) -> None`.
- Produces: deterministic RED contracts for `_secure_manifest_parent()` and descriptor-relative temporary creation.

- [ ] **Step 1: Add the failing parent-swap regression**

Add a test that creates `workspace/evidence` and `outside`, monkeypatches `os.open`, and on the first temporary-file open renames `workspace/evidence` to `workspace/evidence-held` and replaces the lexical path with a symlink to `outside`. Call:

```python
write_release_manifest(
    {"schema_version": 1},
    workspace / "evidence" / "release-manifest.json",
)
```

Require:

```python
assert not (outside / "release-manifest.json").exists()
assert json.loads(
    (workspace / "evidence-held" / "release-manifest.json").read_text("utf-8")
) == {"schema_version": 1}
```

The predecessor code must fail by writing through the swapped lexical path.

- [ ] **Step 2: Add capability and lexical-path RED tests**

Add parameterized tests that monkeypatch the secure-capability predicate false and require `ReleaseEvidenceError` before filesystem mutation, and that reject `Path(".")`, `Path("..") / "manifest.json"`, and a directory destination. Error assertions must match bounded fixed reason classes rather than arbitrary `OSError` text.

- [ ] **Step 3: Add cleanup and synchronization RED tests**

Monkeypatch `os.replace` to fail after the current invocation creates its temporary file. Require the writer to remove that owned temporary entry, preserve an existing destination, and close every opened descriptor. Spy on `os.fsync` and require one file synchronization and one final parent-directory synchronization on success.

- [ ] **Step 4: Run the targeted tests and record RED evidence**

Run:

```bash
uv run pytest \
  tests/test_release_evidence.py::test_write_release_manifest_pins_parent_during_symlink_swap \
  tests/test_release_evidence.py::test_write_release_manifest_fails_without_secure_dir_fd_support \
  tests/test_release_evidence.py::test_write_release_manifest_cleans_owned_temporary_after_replace_failure \
  -q
```

Expected: the parent-swap test exposes an escaped write, the capability test has no fail-closed implementation, and cleanup/synchronization assertions fail.

- [ ] **Step 5: Commit the RED contracts**

```bash
git add tests/test_release_evidence.py
git commit -m "test(release): expose manifest path replacement race"
```

### Task 2: Implement descriptor-relative manifest creation

**Files:**
- Modify: `pg_llm_batch/release_evidence.py`
- Test: `tests/test_release_evidence.py`

**Interfaces:**
- Produces: `_secure_manifest_parent(destination: Path) -> int`, returning an owned descriptor for the final parent directory; `_secure_manifest_writes_supported() -> bool`; unchanged public `write_release_manifest(...) -> None`.

- [ ] **Step 1: Add the secure capability predicate**

Implement:

```python
def _secure_manifest_writes_supported() -> bool:
    required = (os.open, os.mkdir, os.stat, os.unlink, os.replace)
    return (
        all(function in os.supports_dir_fd for function in required)
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
    )
```

`write_release_manifest()` must raise `ReleaseEvidenceError("secure release manifest writes require descriptor-relative no-follow support")` before creating directories when this returns false.

- [ ] **Step 2: Traverse the parent chain by descriptor**

Implement `_secure_manifest_parent(destination)` so absolute paths start from `/`, relative paths start from `.`, `..` is rejected, missing directories are created relative to the current descriptor with mode `0700`, and each next component is opened with:

```python
os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
```

Close the previous descriptor after the next descriptor opens. Convert symlink, non-directory, permission, and unsupported-operation failures to bounded `ReleaseEvidenceError` messages without embedding arbitrary exception text.

- [ ] **Step 3: Bind destination and temporary checks to the final descriptor**

Use `os.stat(name, dir_fd=parent_fd, follow_symlinks=False)` to permit only an absent or regular destination. Reject any existing temporary name. Create the temporary file with:

```python
os.O_CREAT
| os.O_EXCL
| os.O_WRONLY
| os.O_NOFOLLOW
| getattr(os, "O_CLOEXEC", 0)
```

and mode `0o600`; validate `stat.S_ISREG(os.fstat(descriptor).st_mode)`.

- [ ] **Step 4: Write, synchronize, replace, and clean up**

Write canonical UTF-8 through `os.fdopen`, flush, and `os.fsync()` the file. Replace using:

```python
os.replace(
    temporary_name,
    destination_name,
    src_dir_fd=parent_fd,
    dst_dir_fd=parent_fd,
)
os.fsync(parent_fd)
```

Track whether this invocation created the temporary entry. On a later exception, call `os.unlink(temporary_name, dir_fd=parent_fd)` only for that owned entry and ignore only `FileNotFoundError`. Always close `parent_fd`.

- [ ] **Step 5: Run the targeted tests and verify GREEN**

Run:

```bash
uv run pytest tests/test_release_evidence.py -q
```

Expected: all release-evidence tests pass, including the deterministic parent-swap regression.

- [ ] **Step 6: Run focused quality gates**

Run:

```bash
uv run ruff check pg_llm_batch/release_evidence.py tests/test_release_evidence.py
uv run coverage run --branch -m pytest tests/test_release_evidence.py
uv run coverage report --fail-under=100
```

Expected: lint success and 100% statement/branch coverage for the changed production module.

- [ ] **Step 7: Commit the GREEN implementation**

```bash
git add pg_llm_batch/release_evidence.py tests/test_release_evidence.py
git commit -m "fix(release): pin manifest writes to directory descriptors"
```

### Task 3: Make the operator and acquisition contract authoritative

**Files:**
- Modify: `docs/adr/0003-reproducible-release-evidence.md`
- Modify: `docs/doctoring/reproducible-release-evidence.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_release_evidence_documentation.py`

**Interfaces:**
- Consumes: descriptor-relative writer contract from Task 2.
- Produces: authoritative operator guidance and deterministic documentation tests.

- [ ] **Step 1: Add documentation contract tests**

Require the ADR and doctoring note to state that the writer uses directory-descriptor-relative no-follow traversal, fails closed on unsupported platforms, synchronizes the file and parent directory, cleans only its own temporary entry, and does not protect a lexical path after the function returns. Require APA references to Python 3.14 `os`, POSIX.1-2024 `openat`/`renameat`, and MITRE CWE-367.

- [ ] **Step 2: Run the documentation tests and verify RED**

```bash
uv run pytest tests/test_release_evidence_documentation.py -q
```

Expected: failure until the authoritative documents contain every new contract term.

- [ ] **Step 3: Update ADR, doctoring, and changelog**

Document the descriptor chain, `O_NOFOLLOW`, fixed unsupported-platform error, temporary ownership, two `fsync` boundaries, residual same-UID post-return limitation, rollback to PR #55 behavior, and incident triage. Add an Unreleased security fix without changing version `0.1.0`.

- [ ] **Step 4: Run documentation and release-evidence tests**

```bash
uv run pytest \
  tests/test_release_evidence.py \
  tests/test_release_evidence_documentation.py \
  -q
```

Expected: all pass.

- [ ] **Step 5: Commit the authoritative contract**

```bash
git add CHANGELOG.md docs/adr/0003-reproducible-release-evidence.md \
  docs/doctoring/reproducible-release-evidence.md \
  tests/test_release_evidence_documentation.py
git commit -m "docs(release): govern descriptor-bound manifest evidence"
```

### Task 4: Verify the exact stacked head and open a draft PR

**Files:**
- Verify: all tracked files on `agent/release-evidence-dirfd-hardening`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: exact-head CI/review evidence stacked on PR #55, without treating it as final `main` merge evidence.

- [ ] **Step 1: Run the complete deterministic suite**

```bash
uv run pytest -q
uv run ruff check .
uv run coverage run --branch -m pytest
uv run coverage report --fail-under=100
uv build
```

Expected: complete success, 100% production statement/branch/docstring coverage, and valid wheel/sdist construction.

- [ ] **Step 2: Confirm repository cleanliness**

```bash
git status --short
```

Expected: no generated coverage databases, build products, caches, or other local evidence artifacts tracked or untracked.

- [ ] **Step 3: Open a draft stacked PR**

Open the PR with base `agent/reproducible-release-acceptance`. Record the exact head and base SHAs, RED and GREEN commits, exact CI and Release Acceptance runs, zero unresolved threads, dependency order `#790 -> #53 -> #55 -> new PR`, and the requirement to retarget to integrated `main` and rerun every default-branch gate before merge.

- [ ] **Step 4: Request exact-head CodeRabbit review**

Request one review tied to the exact head/base. Distinguish rate limits and predecessor-head comments from actionable current-head findings. Apply valid findings test-first and repeat exact-head verification.

- [ ] **Step 5: Stop at protected dependency gates**

Do not mark ready, merge, version-bump, publish, or attest while PR #55 is draft or any prerequisite approval/check is absent.
