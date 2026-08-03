# Commercial CI and Hourly Maintenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add repository-owned commercial quality gates and an hourly PR repair/review/merge heartbeat without duplicating the organization’s privileged automation.

**Architecture:** Keep deterministic package, documentation, coverage, and container checks in this repository. Delegate privileged review repair and merge decisions to immutable revisions of the hardened reusable workflows in `ContextualWisdomLab/.github`, called by a least-privilege hourly workflow and refreshed through Dependabot.

**Tech Stack:** GitHub Actions, Python 3.10/3.12/3.14, uv, pytest, pytest-cov, Ruff, Interrogate, Docker Compose, reusable organization workflows, Dependabot.

## Global Constraints

- Every production Python symbol must retain docstring coverage of exactly 100%.
- Line coverage must fail below exactly 100%.
- Every external GitHub Action and reusable workflow must be pinned to an immutable 40-character commit SHA.
- The hourly maintenance cadence is minute 17 of every UTC hour.
- Privileged repair and merge implementation remains centralized in `ContextualWisdomLab/.github`.
- Database object naming is unchanged; no database object is introduced by this plan.

---

### Task 1: Define executable workflow contracts

**Files:**
- Create: `tests/test_workflow_contracts.py`

**Interfaces:**
- Consumes: `.github/workflows/ci.yml`, `.github/workflows/hourly-maintenance.yml`, `.github/dependabot.yml`, and `pyproject.toml`.
- Produces: four standard-library-only pytest tests that reject schedule drift, mutable workflow references, missing dependency-update coverage, missing compatibility/build gates, or weakened quality thresholds.

- [x] **Step 1: Write failing workflow contract tests**

```python
def test_ci_workflow_enforces_supported_versions_and_quality_gates() -> None:
    workflow = _read(".github/workflows/ci.yml")
    assert 'python-version: ["3.10", "3.12", "3.14"]' in workflow
    assert "--cov-fail-under=100" in workflow
    assert "interrogate --fail-under 100 pg_llm_batch" in workflow
    assert "uv build --no-sources" in workflow
```

- [x] **Step 2: Require immutable workflow dependencies**

```python
def _assert_external_actions_are_pinned(workflow: str) -> None:
    for raw_line in workflow.splitlines():
        line = raw_line.strip()
        if line.startswith("uses:"):
            assert re.search(r"@[0-9a-f]{40}(?:\\s|$)", line)
```

- [x] **Step 3: Require GitHub Actions dependency updates**

```python
def test_dependabot_tracks_the_new_github_actions_manifests() -> None:
    configuration = _read(".github/dependabot.yml")
    assert 'package-ecosystem: "github-actions"' in configuration
    assert "dependency_file_not_found" not in configuration
```

- [x] **Step 4: Run the contract tests before implementation**

Run: `python -m pytest -q tests/test_workflow_contracts.py`

Expected: failures because the workflows, GitHub Actions update entry, and threshold tables do not yet exist.

- [x] **Step 5: Keep the contract dependency-free**

Use only Python 3.10 standard-library modules such as `pathlib` and `re`; assert the small TOML contract text directly instead of importing a version-specific TOML parser.

- [x] **Step 6: Commit the red contract**

```bash
git add tests/test_workflow_contracts.py
git commit -m "test(ci): define commercial workflow contracts"
```

### Task 2: Add deterministic repository CI

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `pyproject.toml`, `uv.lock`, Python package/tests, root `Dockerfile`, `docker/postgres/Dockerfile`, and `docker-compose.yml`.
- Produces: required-check candidates named `Unit tests (Python …)`, `Coverage, docstrings, lint, and package`, and `Container builds`.

- [x] **Step 1: Add the supported-Python matrix**

Run `uv sync --locked` and `uv run pytest -q -m "not integration"` on Python 3.10, 3.12, and 3.14.

- [x] **Step 2: Add the quality gate job**

Run, in order:

```bash
uv sync --locked
uv run python -m compileall -q pg_llm_batch
uv run ruff check pg_llm_batch tests
uvx --from 'interrogate==1.7.0' interrogate --fail-under 100 pg_llm_batch
uv run --with pytest-cov==7.1.0 pytest -q -m "not integration" --cov=pg_llm_batch --cov-report=term-missing --cov-fail-under=100
uv lock --check
uv build --no-sources
```

- [x] **Step 3: Add container validation**

```bash
docker compose config >/dev/null
docker build --tag pg-llm-batch:ci .
docker build --tag pg-llm-batch-postgres:ci docker/postgres
```

- [x] **Step 4: Apply workflow security controls**

Set `contents: read`, disable persisted checkout credentials, use concurrency cancellation, and pin every third-party action to a 40-character SHA.

- [x] **Step 5: Commit CI**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add deterministic commercial quality gates"
```

### Task 3: Add the hourly maintenance heartbeat

**Files:**
- Create: `.github/workflows/hourly-maintenance.yml`
- Modify: `.github/dependabot.yml`

**Interfaces:**
- Consumes: immutable revisions of `pr-review-fix-scheduler.yml` and `pr-review-merge-scheduler.yml` from `ContextualWisdomLab/.github`.
- Produces: one bounded hourly maintenance run for `ContextualWisdomLab/pg-llm-batch` plus weekly reviewed updates for all pinned workflow dependencies.

- [x] **Step 1: Schedule the workflow**

```yaml
on:
  schedule:
    - cron: "17 * * * *"
  workflow_dispatch:
```

- [x] **Step 2: Call the central review-fix scheduler at an immutable revision**

Pass the repository, `main`, a one-dispatch budget, and a one-hour retry window. Scope permissions to Actions write, issue write, and pull-request/status reads.

- [x] **Step 3: Call the central merge scheduler at the same immutable revision**

Use `if: ${{ always() }}` so queue reevaluation still occurs when repair dispatch is temporarily unavailable. Enable review dispatch, stale-branch updates, auto-merge, and `direct_or_auto` behavior.

- [x] **Step 4: Re-enable GitHub Actions Dependabot coverage**

```yaml
- package-ecosystem: "github-actions"
  directory: "/"
  schedule:
    interval: "weekly"
  open-pull-requests-limit: 10
```

- [x] **Step 5: Commit the scheduler and dependency-maintenance changes**

```bash
git add .github/workflows/hourly-maintenance.yml .github/dependabot.yml
git commit -m "ci: pin and maintain hourly workflow dependencies"
```

### Task 4: Codify hard quality thresholds

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: coverage.py and Interrogate configuration loaders.
- Produces: repository-level threshold configuration shared by local and CI execution.

- [x] **Step 1: Configure line coverage**

```toml
[tool.coverage.run]
source = ["pg_llm_batch"]
omit = ["tests/*"]

[tool.coverage.report]
fail_under = 100
show_missing = true
```

- [x] **Step 2: Configure docstring coverage**

```toml
[tool.interrogate]
exclude = ["tests"]
fail-under = 100
```

- [x] **Step 3: Commit threshold configuration**

```bash
git add pyproject.toml
git commit -m "ci: codify 100 percent quality thresholds"
```

### Task 5: Document architecture and verify the full change

**Files:**
- Create: `docs/superpowers/specs/2026-08-03-commercial-ci-hourly-loop-design.md`
- Create: `docs/superpowers/plans/2026-08-03-commercial-ci-hourly-loop.md`

**Interfaces:**
- Consumes: the implemented workflow names, schedules, permissions, immutable references, update mechanism, and quality commands.
- Produces: an auditable design rationale and executable implementation checklist.

- [x] **Step 1: Record the design and trade-offs**

Explain why local CI plus pinned central privileged workflows is preferred to either central-only verification, copied automation, or mutable branch references.

- [x] **Step 2: Run the workflow contracts after implementation**

Run: `python -m pytest -q tests/test_workflow_contracts.py`

Expected: `4 passed`.

- [x] **Step 3: Parse both workflow files as YAML**

Run a safe YAML parser against `.github/workflows/ci.yml` and `.github/workflows/hourly-maintenance.yml`.

Expected: both documents parse successfully.

- [ ] **Step 4: Inspect every current-head check**

Inspect CodeRabbit/OpenCode feedback, local CI, SAST, and Security Scan on the current PR head. Fix actionable current-head failures and rerun checks.

- [ ] **Step 5: Merge only the reviewed current head and re-check the queue**

After current-head validation, merge the PR, query open PRs again, and continue the maintenance loop until the repository returns zero open PRs.
