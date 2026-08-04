# PEP 639 License Metadata Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace deprecated Python package license metadata with a normalized PEP 639 SPDX expression and explicit legal-file contract.

**Architecture:** Keep setuptools as the build backend, raise its minimum to the documented PEP 639-compatible version, declare `Apache-2.0` and the legal files in `pyproject.toml`, and enforce the contract through source, installed-metadata, and built-artifact verification.

**Tech Stack:** Python 3.10+, setuptools, uv, importlib.metadata, pytest, zipfile, tarfile, Ruff, Interrogate, GitHub Actions.

## Global constraints

- The license remains Apache-2.0.
- `LICENSE` and `NOTICE` must be shipped in both wheel and source archives.
- `project.license` must be a string SPDX expression, never a legacy table.
- `project.license-files` must explicitly list both legal files.
- The minimum setuptools backend must be at least 77.0.3.
- No deprecated `License ::` classifier may be introduced.
- Runtime dependencies and public APIs remain unchanged.
- Python 3.10, 3.12, and 3.14 remain supported.
- Production statement, branch, and docstring coverage remain 100%.

---

### Task 1: Define the failing packaging contract

**Files:**
- Create: `tests/test_packaging_metadata.py`
- Create temporarily: `.github/workflows/one-shot-pep639-red.yml`
- Create after execution: `docs/superpowers/evidence/2026-08-04-pep639-license-red.md`

- [ ] **Step 1: Add the source metadata contract**

```python
def test_pyproject_uses_pep639_license_metadata() -> None:
    project = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'requires = ["setuptools>=77.0.3", "wheel"]' in project
    assert 'license = "Apache-2.0"' in project
    assert 'license-files = ["LICENSE", "NOTICE"]' in project
    assert "license = {" not in project
    assert "License ::" not in project
```

This must fail on the current legacy `license = { text = ... }` table and old setuptools floor.

- [ ] **Step 2: Add the installed metadata contract**

```python
def test_installed_distribution_exposes_normalized_license_metadata() -> None:
    package_metadata = metadata("pg-llm-batch")
    assert package_metadata["License-Expression"] == "Apache-2.0"
    assert set(package_metadata.get_all("License-File") or ()) == {
        "LICENSE",
        "NOTICE",
    }
    assert package_metadata.get("License") is None
```

This must fail before the migration because the editable distribution exposes the legacy metadata form.

- [ ] **Step 3: Run only the new tests before production changes**

```bash
uv sync --locked
set +e
uv run pytest -q tests/test_packaging_metadata.py 2>&1 | tee /tmp/pep639-red.log
status=${PIPESTATUS[0]}
set -e
if [ "$status" -eq 0 ]; then
  echo "Expected PEP 639 tests to fail before implementation" >&2
  exit 1
fi
grep -Eq 'setuptools>=77\.0\.3|License-Expression|license-files' /tmp/pep639-red.log
```

Expected: non-zero pytest status for the intended source and installed-metadata mismatches.

- [ ] **Step 4: Record red evidence and remove the temporary workflow**

Record the exact pre-implementation head, command, exit status, and assertion categories in `docs/superpowers/evidence/2026-08-04-pep639-license-red.md`. Delete the temporary workflow in the same commit.

### Task 2: Implement the PEP 639 source contract

**Files:**
- Modify: `pyproject.toml`
- Test: `tests/test_packaging_metadata.py`

- [ ] **Step 1: Raise the build-backend floor**

Change:

```toml
requires = ["setuptools>=68", "wheel"]
```

To:

```toml
requires = ["setuptools>=77.0.3", "wheel"]
```

- [ ] **Step 2: Replace the legacy license table**

Change:

```toml
license = { text = "Apache-2.0" }
```

To:

```toml
license = "Apache-2.0"
license-files = ["LICENSE", "NOTICE"]
```

- [ ] **Step 3: Run focused tests**

```bash
uv sync --locked
uv run pytest -q tests/test_packaging_metadata.py
```

Expected: both tests pass on the editable package metadata.

### Task 3: Verify built artifacts and update release history

**Files:**
- Modify: `CHANGELOG.md`
- Inspect generated: `dist/*.whl`, `dist/*.tar.gz`

- [ ] **Step 1: Record the migration**

Add under `Unreleased / Changed`:

```markdown
- Migrated package licensing to PEP 639 with an SPDX `Apache-2.0` expression,
  explicit `LICENSE` and `NOTICE` files, and a compatible setuptools backend
  floor so built artifacts expose normalized legal metadata without warnings.
```

- [ ] **Step 2: Build clean artifacts**

```bash
rm -rf dist
uv build --no-sources
```

Expected: wheel and source distribution build without the legacy license-table deprecation warning.

- [ ] **Step 3: Inspect artifact metadata and contents**

Use Python's `zipfile`, `tarfile`, and `email.parser` to require:

```text
License-Expression: Apache-2.0
License-File: LICENSE
License-File: NOTICE
*.dist-info/licenses/LICENSE
*.dist-info/licenses/NOTICE
<sdist-root>/LICENSE
<sdist-root>/NOTICE
```

Fail if any file or metadata field is absent or duplicated unexpectedly.

### Task 4: Run full quality, security, review, and merge gates

**Files:**
- No additional production paths.

- [ ] **Step 1: Run complete local-equivalent gates**

```bash
uv sync --locked
uv run pytest -q -m "not integration"
uv run python -m compileall -q pg_llm_batch
uv run ruff check pg_llm_batch tests
uvx --from 'interrogate==1.7.0' interrogate --fail-under 100 pg_llm_batch
uv run --with pytest-cov==7.1.0 pytest -q -m "not integration" \
  --cov=pg_llm_batch --cov-report=term-missing --cov-fail-under=100
uv lock --check
uv build --no-sources
docker compose config >/dev/null
docker build --tag pg-llm-batch:pep639 .
docker build --tag pg-llm-batch-postgres:pep639 docker/postgres
```

Expected: every command exits zero, including 100% production statement, branch, and docstring coverage.

- [ ] **Step 2: Open or update the PR with exact evidence**

Include red head, final head, focused/full test counts, metadata fields, archive contents, warning-free build status, coverage totals, standards basis, and release decision.

- [ ] **Step 3: Inspect all current-head review sources**

Require no actionable human, CodeRabbit, security, or inline review findings. Resolve only findings actually addressed.

- [ ] **Step 4: Require exact-head hosted workflows**

Require successful CI, SAST Semgrep, and Security Scan. Queued, pending, action-required, cancelled, or unexpectedly skipped is not success.

- [ ] **Step 5: Merge with exact-head binding**

Use the repository-supported merge method with the reviewed head SHA and re-query the PR queue. Continue to the next release-readiness or buyer-visible gap only after the queue returns to zero.
