# Checkpoint Migration Operator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one opt-in operator command that validates, serializes, atomically applies, and reports the durable checkpoint plus checkpoint-audit PostgreSQL migrations.

**Architecture:** A focused `checkpoint_migrations` module loads both canonical SQL files before database access, creates immutable bounded descriptors, obtains one fixed transaction-level PostgreSQL advisory lock, executes migration 0007 before 0008, and commits once. The existing separate helpers and `init-db` remain unchanged; the new CLI command emits bounded JSON evidence only after commit.

**Tech Stack:** Python 3.10+, psycopg 3, PostgreSQL 18 advisory locks and transaction semantics, argparse, hashlib, pytest, GitHub Actions, existing uv/coverage/Ruff toolchain.

## Global Constraints

- Base exact head: `2820aa36d8dedf7d89d1b745e5728acf3b913d2b` from stacked PR #62.
- Branch: `agent/checkpoint-migration-operator`; do not add a competing writer or temporary repair workflow.
- Preserve `init-db`, `apply_result_checkpoint_schema()`, and `apply_result_checkpoint_audit_schema()` behavior.
- Load both canonical migration files before database connection.
- Accept only non-empty files of at most 1,048,576 bytes each.
- Execute `0007_result_stream_checkpoints` before `0008_result_checkpoint_audit_events` under one transaction-level advisory lock and one commit.
- Emit no DSN, credential, SQL body, provider body, tenant, checkpoint, audit-row, or raw database-error data in success evidence.
- Keep every database object name descriptive and snake_case.
- Maintain 100% production statement, branch, and public-docstring coverage.
- Update AGENTS.md, CLAUDE.md, ARCHITECTURE.md, CHANGELOG.md, README.md, ADR, operator documentation, and doctoring when the contract changes.
- No version bump or release publication until the integrated exact head passes every repository gate and independent approval.

---

### Task 1: Establish the RED migration coordinator contract

**Files:**
- Create: `tests/test_checkpoint_migration_operator.py`
- Modify: `tests/test_bootstrap_cli.py`

**Interfaces:**
- Consumes: canonical paths `checkpoint_store.MIGRATION_PATH` and `checkpoint_audit.AUDIT_MIGRATION_PATH`.
- Produces: required public names `CheckpointSchemaMigration`, `plan_checkpoint_schema_migrations()`, and `apply_checkpoint_schema_migrations(postgres_dsn)` plus CLI command `init-checkpoint-storage`.

- [ ] **Step 1: Write the failing public contract tests**

```python
from hashlib import sha256
from pg_llm_batch import (
    CheckpointSchemaMigration,
    apply_checkpoint_schema_migrations,
    plan_checkpoint_schema_migrations,
)


def test_plan_uses_canonical_order_and_digests():
    plan = plan_checkpoint_schema_migrations()
    assert [item.migration_id for item in plan] == [
        "0007_result_stream_checkpoints",
        "0008_result_checkpoint_audit_events",
    ]
    assert all(isinstance(item, CheckpointSchemaMigration) for item in plan)
    assert plan[0].sha256 == sha256(MIGRATION_PATH.read_bytes()).hexdigest()
```

Add tests proving immutable descriptors, positive byte counts, lowercase 64-byte hex digests, non-empty/1 MiB bounds before `psycopg.connect`, one advisory lock before SQL, exact SQL order, one commit, and no commit after the second statement fails.

- [ ] **Step 2: Add the failing CLI route test**

```python
def test_checkpoint_storage_initialization_emits_bounded_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "apply_checkpoint_schema_migrations", lambda dsn: plan)
    assert cli._dispatch([
        "init-checkpoint-storage", "--dsn", "postgresql://x"
    ]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1,
        "applied_migrations": [descriptor.as_dict() for descriptor in plan],
    }
```

- [ ] **Step 3: Run the exact RED tests**

Run:

```bash
uv run pytest -q \
  tests/test_checkpoint_migration_operator.py \
  tests/test_bootstrap_cli.py
```

Expected: collection or import failure because `checkpoint_migrations` and its public exports do not exist.

- [ ] **Step 4: Commit the RED contract**

```bash
git add tests/test_checkpoint_migration_operator.py tests/test_bootstrap_cli.py
git commit -m "test(migrations): require atomic checkpoint schema operator"
```

### Task 2: Implement bounded planning and atomic application

**Files:**
- Create: `pg_llm_batch/checkpoint_migrations.py`
- Modify: `pg_llm_batch/__init__.py`

**Interfaces:**
- Consumes: `checkpoint_store.MIGRATION_PATH`, `checkpoint_audit.AUDIT_MIGRATION_PATH`, `db._require_psycopg`, and `db.psycopg`.
- Produces:
  - `CheckpointSchemaMigration(migration_id: str, byte_count: int, sha256: str)`
  - `plan_checkpoint_schema_migrations() -> tuple[CheckpointSchemaMigration, ...]`
  - `apply_checkpoint_schema_migrations(postgres_dsn: str) -> tuple[CheckpointSchemaMigration, ...]`

- [ ] **Step 1: Implement the immutable public descriptor**

```python
@dataclass(frozen=True, slots=True)
class CheckpointSchemaMigration:
    """Describe one bounded canonical checkpoint-storage migration."""

    migration_id: str
    byte_count: int
    sha256: str

    def as_dict(self) -> dict[str, int | str]:
        """Return a stable JSON-compatible evidence object."""
        return {
            "migration_id": self.migration_id,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
        }
```

Validate exact supported identifiers, positive byte count at most 1 MiB, and lowercase 64-character hexadecimal SHA-256 without coercion.

- [ ] **Step 2: Load and hash all canonical SQL before database access**

```python
def _load_checkpoint_schema_migrations() -> tuple[_LoadedMigration, ...]:
    loaded = []
    for migration_id, path in _CHECKPOINT_SCHEMA_MIGRATION_PATHS:
        sql_bytes = path.read_bytes()
        if not sql_bytes or len(sql_bytes) > MAX_CHECKPOINT_SCHEMA_MIGRATION_BYTES:
            raise RuntimeError("checkpoint schema migration has an invalid bounded size")
        loaded.append(_LoadedMigration(
            descriptor=CheckpointSchemaMigration(
                migration_id=migration_id,
                byte_count=len(sql_bytes),
                sha256=hashlib.sha256(sql_bytes).hexdigest(),
            ),
            sql=sql_bytes.decode("utf-8", errors="strict"),
        ))
    return tuple(loaded)
```

Keep `_LoadedMigration.sql` private so public evidence never exposes SQL text.

- [ ] **Step 3: Apply the plan under one transaction-level advisory lock**

```python
def apply_checkpoint_schema_migrations(postgres_dsn: str):
    """Apply checkpoint and audit schema atomically in canonical order."""
    loaded = _load_checkpoint_schema_migrations()
    _require_psycopg()
    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)",
                (
                    CHECKPOINT_SCHEMA_MIGRATION_LOCK_NAMESPACE,
                    CHECKPOINT_SCHEMA_MIGRATION_LOCK_OPERATION,
                ),
            )
            for migration in loaded:
                cursor.execute(migration.sql)
        connection.commit()
    return tuple(migration.descriptor for migration in loaded)
```

Use constants `1346849869` (`PGLM`) and `1111577672` (`BATH`) as the reviewed two-key lock namespace. Do not catch and reclassify database exceptions with raw messages.

- [ ] **Step 4: Export the public contract**

Add all three public names to `pg_llm_batch.__init__` and `__all__`, and describe the coordinator in the module-level public API docstring.

- [ ] **Step 5: Run focused tests and refactor**

Run:

```bash
uv run pytest -q tests/test_checkpoint_migration_operator.py
uv run ruff check pg_llm_batch/checkpoint_migrations.py tests/test_checkpoint_migration_operator.py
```

Expected: PASS with every production branch covered by focused tests.

- [ ] **Step 6: Commit the GREEN implementation**

```bash
git add pg_llm_batch/checkpoint_migrations.py pg_llm_batch/__init__.py
git commit -m "feat(migrations): apply checkpoint schemas atomically"
```

### Task 3: Add the explicit operator CLI

**Files:**
- Modify: `pg_llm_batch/cli.py`
- Modify: `tests/test_bootstrap_cli.py`

**Interfaces:**
- Consumes: `apply_checkpoint_schema_migrations(postgres_dsn)` and each descriptor's `as_dict()`.
- Produces: `python -m pg_llm_batch init-checkpoint-storage --dsn ...`.

- [ ] **Step 1: Add parser and dispatch behavior**

```python
p_checkpoint = sub.add_parser(
    "init-checkpoint-storage",
    help="Atomically apply checkpoint and checkpoint-audit schemas",
)
_add_common(p_checkpoint)
```

Dispatch only after DSN resolution:

```python
if args.command == "init-checkpoint-storage":
    applied = apply_checkpoint_schema_migrations(dsn)
    print(json.dumps({
        "schema_version": 1,
        "applied_migrations": [item.as_dict() for item in applied],
    }, separators=(",", ":"), sort_keys=True))
    return 0
```

- [ ] **Step 2: Verify canonical output and unchanged init-db routing**

Run:

```bash
uv run pytest -q tests/test_bootstrap_cli.py
```

Expected: PASS. Existing `init-db` test still observes only `db.apply_schema`.

- [ ] **Step 3: Commit the CLI**

```bash
git add pg_llm_batch/cli.py tests/test_bootstrap_cli.py
git commit -m "feat(cli): add checkpoint storage migration command"
```

### Task 4: Prove live rollback and serialization

**Files:**
- Create: `tests/test_checkpoint_migration_operator_integration.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_checkpoint_audit_ci_contract.py`

**Interfaces:**
- Consumes: public migration coordinator and internal canonical migration path tuple via monkeypatch for bounded fault injection.
- Produces: permanent live PostgreSQL all-or-nothing and advisory-lock evidence.

- [ ] **Step 1: Write live all-or-nothing regression**

Create a random temporary database. Copy migration 0007 to a temporary file and use an invalid second SQL file. Invoke the coordinator and require a PostgreSQL error. Reconnect as owner and assert both
`to_regclass('public.llm_result_stream_checkpoints')` and
`to_regclass('public.llm_result_checkpoint_audit_events')` are `NULL`.

- [ ] **Step 2: Write live lock serialization regression**

Hold the same two-key `pg_advisory_xact_lock` in one connection. Start the coordinator in a second thread, require it not to complete while the first transaction holds the lock, release the first transaction, and require successful completion. Use bounded thread events and timeouts; always terminate the temporary database sessions in cleanup.

- [ ] **Step 3: Add the exact file to the permanent PostgreSQL job**

Change only the checkpoint-audit integration command to:

```yaml
run: >-
  uv run pytest -q
  tests/test_checkpoint_audit_integration.py
  tests/test_checkpoint_migration_operator_integration.py
  -m integration
```

Update the workflow contract test so it binds this exact folded command to the exact `checkpoint-audit-integration` job and cannot borrow strings from another job.

- [ ] **Step 4: Run live verification**

Run:

```bash
PG_LLM_BATCH_TEST_DSN=postgresql://postgres:postgres@localhost:5432/postgres \
  uv run pytest -q \
  tests/test_checkpoint_audit_integration.py \
  tests/test_checkpoint_migration_operator_integration.py \
  -m integration
```

Expected: PASS; no temporary database or role remains.

- [ ] **Step 5: Commit live evidence**

```bash
git add \
  tests/test_checkpoint_migration_operator_integration.py \
  tests/test_checkpoint_audit_ci_contract.py \
  .github/workflows/ci.yml
git commit -m "test(migrations): prove rollback and advisory serialization"
```

### Task 5: Make the operator contract authoritative

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `ARCHITECTURE.md`
- Modify: `CHANGELOG.md`
- Create: `docs/adr/0010-atomic-checkpoint-schema-operator.md`
- Create: `docs/checkpoint-storage-migrations.md`
- Create: `docs/doctoring/checkpoint-migration-operator.md`
- Create: `tests/test_checkpoint_migration_operator_documentation.py`

**Interfaces:**
- Consumes: final production and CLI contracts.
- Produces: beginner-readable operator workflow, design authority, failure recovery, and APA 7 evidence.

- [ ] **Step 1: Write the failing documentation contract**

Require each authoritative file to state all of:

- explicit opt-in `init-checkpoint-storage`;
- canonical 0007 → 0008 order;
- both files loaded before database access;
- one transaction-level advisory lock and automatic release;
- one transaction and one commit;
- second-migration failure rolls back the first;
- digest evidence is not signature or attestation;
- `init-db` and separate helpers remain compatible; and
- no migration ledger, downgrade, deletion, or retained-evidence rollback.

- [ ] **Step 2: Update public and contributor documentation**

Add a quick-start command and architecture flow:

```text
init-checkpoint-storage
    ├─ load + bound + hash migration 0007
    ├─ load + bound + hash migration 0008
    ├─ pg_advisory_xact_lock(PGLM, BATH)
    ├─ execute 0007 → 0008
    └─ commit once → bounded JSON evidence
```

- [ ] **Step 3: Record standards in APA 7 form**

Use NIST SP 800-53 Rev. 5 CM-3/CM-3(2), PostgreSQL 18 system administration functions, transactions, and ROLLBACK documentation. Explain that advisory locking coordinates cooperating operator invocations and does not stop a privileged actor from executing unrelated SQL outside the package boundary.

- [ ] **Step 4: Run documentation and focused test gates**

Run:

```bash
uv run pytest -q \
  tests/test_checkpoint_migration_operator.py \
  tests/test_checkpoint_migration_operator_integration.py \
  tests/test_checkpoint_migration_operator_documentation.py \
  tests/test_bootstrap_cli.py \
  tests/test_checkpoint_audit_ci_contract.py
```

Expected: PASS.

- [ ] **Step 5: Commit authoritative documentation**

```bash
git add README.md AGENTS.md CLAUDE.md ARCHITECTURE.md CHANGELOG.md \
  docs/adr/0010-atomic-checkpoint-schema-operator.md \
  docs/checkpoint-storage-migrations.md \
  docs/doctoring/checkpoint-migration-operator.md \
  tests/test_checkpoint_migration_operator_documentation.py
git commit -m "docs(migrations): define atomic operator contract"
```

### Task 6: Exact-head verification and draft PR gate

**Files:**
- Update: pull-request description only after exact-head evidence exists.

**Interfaces:**
- Consumes: complete branch.
- Produces: one stacked draft PR targeting `agent/checkpoint-audit-trail`.

- [ ] **Step 1: Run deterministic local gates**

```bash
uv sync --locked --extra test
uv run ruff check .
uv run python -m compileall -q pg_llm_batch tests
uv run pytest -q -m "not integration" \
  --cov=pg_llm_batch --cov-branch --cov-report=term-missing \
  --cov-fail-under=100
```

Require 100% production statement and branch coverage, 100% public docstrings,
lock freshness, package build, Compose validation, and no generated artifacts.

- [ ] **Step 2: Open one stacked draft PR**

Target `agent/checkpoint-audit-trail`. Record exact head and exact base SHAs, RED
and GREEN runs, no unresolved valid feedback, and the dependency order:

```text
.github#790 -> #53 -> #55 -> #56 -> #57 -> #58 -> #59 -> #60 -> #61 -> #62 -> this PR
```

- [ ] **Step 3: Inspect every exact-head check and review**

Do not count queued, pending, cancelled, skipped-required, absent, stale-head,
stale-base, synthetic-merge-only, or infrastructure-only evidence as success.
Address every valid human, CodeRabbit, OpenCode, Noema, Dependabot, code-scanning,
security, and supply-chain finding test-first.

- [ ] **Step 4: Keep the PR draft and unmerged**

Do not mark ready, version-bump, publish, attest, or merge until all prerequisites
are integrated into `main`, this branch is reconciled onto that exact integrated
base, every required current-head/current-base gate succeeds, unresolved valid
findings are zero, and a qualifying independent non-author GitHub `APPROVED`
review exists.
