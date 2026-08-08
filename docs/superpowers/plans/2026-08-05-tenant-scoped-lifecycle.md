# Tenant-Scoped Durable Lifecycle Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a trusted tenant-qualified lifecycle identity and fail-closed PostgreSQL row isolation while preserving the existing standalone durable-client API.

**Architecture:** Extend the single authoritative `llm_remote_batch_jobs` projection with a validated `tenant_scope`, migrate legacy rows to an explicit `standalone` scope, and enforce transaction-local PostgreSQL row-level security. Keep the old recorder seam intact and introduce a tenant-aware subclass that overrides only recorder dispatch. All reads and writes bind tenant scope through parameterized `set_config(..., true)` before touching lifecycle rows.

**Tech Stack:** Python 3.10+, PostgreSQL 18 SQL, psycopg 3, pytest/pytest-asyncio, Ruff, coverage.py, Docker Compose, GitHub Actions.

## Global Constraints

- `tenant_scope` must match `[A-Za-z0-9][A-Za-z0-9._:-]{0,127}` exactly; no trimming or coercion.
- Existing `DurableBatchAPIClient` and `LifecycleRecorder` signatures remain source-compatible.
- Existing lifecycle rows migrate to exact scope `standalone` without deletion or identity merging.
- RLS must be both enabled and forced; missing transaction scope must be default-deny.
- Superuser and `BYPASSRLS` exceptions must be documented rather than overstated.
- All SQL values remain parameter-bound; no tenant value enters dynamic SQL.
- Database object names use descriptive multi-word `snake_case`.
- Generated coverage databases, caches, and build artifacts remain ignored and untracked.
- Production statement, branch, and public-docstring coverage remain 100%.
- No temporary write-capable workflow is introduced; ordinary repository CI supplies verification.

---

### Task 1: Define strict tenant-scope validation

**Files:**
- Modify: `pg_llm_batch/db.py`
- Create: `tests/test_tenant_scope_validation.py`

**Interfaces:**
- Produces: `DEFAULT_TENANT_SCOPE: str`, `MAX_TENANT_SCOPE_CHARACTERS: int`, `TENANT_SCOPE_PATTERN: Pattern[str]`, and `validate_tenant_scope(value: Any) -> str`.
- Consumes: existing `ValidationError` structured diagnostics.

- [ ] **Step 1: Write failing boundary tests**

Create parametrized tests proving that `standalone`, `tenant-a`, `Tenant_01`, and a 128-character ASCII value are accepted unchanged. Add rejected cases for `None`, booleans, empty text, leading/trailing spaces, slash, percent escape, control/NUL, Unicode, and 129 characters. Assert `ValidationError.details["field"] == "tenant_scope"` and that no rejected value is coerced.

- [ ] **Step 2: Run the focused tests and preserve RED evidence**

Run:

```bash
pytest -q tests/test_tenant_scope_validation.py
```

Expected: collection or import failure because the new constants and validator do not exist.

- [ ] **Step 3: Implement the minimal validator**

Add:

```python
MAX_TENANT_SCOPE_CHARACTERS = 128
DEFAULT_TENANT_SCOPE = "standalone"
TENANT_SCOPE_PATTERN = re.compile(
    rf"[A-Za-z0-9][A-Za-z0-9._:-]{{0,{MAX_TENANT_SCOPE_CHARACTERS - 1}}}\Z"
)


def validate_tenant_scope(value: Any) -> str:
    """Validate one trusted local tenant scope without coercion.

    Args:
        value: Host-authorized tenant identifier used for lifecycle isolation.

    Returns:
        The exact validated ASCII tenant scope.

    Raises:
        ValidationError: If the value is not a supported 1-128 character scope.
    """
    if not isinstance(value, str) or TENANT_SCOPE_PATTERN.fullmatch(value) is None:
        raise ValidationError(
            field="tenant_scope",
            value=value,
            reason=(
                "must be 1-128 ASCII characters beginning with an alphanumeric "
                "character and containing only letters, digits, dot, underscore, "
                "colon, or hyphen"
            ),
        )
    return value
```

- [ ] **Step 4: Run validator tests and lint**

```bash
pytest -q tests/test_tenant_scope_validation.py
ruff check pg_llm_batch/db.py tests/test_tenant_scope_validation.py
```

Expected: PASS.

- [ ] **Step 5: Commit the validator slice**

```bash
git add pg_llm_batch/db.py tests/test_tenant_scope_validation.py
git commit -m "feat(tenant): validate lifecycle tenant scopes"
```

### Task 2: Add migration-safe tenant identity and forced RLS

**Files:**
- Modify: `pg_llm_batch/schema.sql`
- Modify: `docker/postgres/init/02_schema.sql`
- Modify: `tests/test_remote_batch_lifecycle.py`
- Modify: `tests/test_schema_integrity.py`
- Create: `tests/test_tenant_lifecycle_schema.py`

**Interfaces:**
- Produces: column `tenant_scope`, constraint `ck_llm_remote_batch_jobs_tenant_scope`, unique constraint `uq_llm_remote_batch_jobs_tenant_endpoint_id`, index `idx_llm_remote_batch_jobs_tenant_status_observed`, and policy `plc_llm_remote_batch_jobs_tenant_scope`.
- Consumes: `DEFAULT_TENANT_SCOPE == "standalone"` and the exact scope regex from Task 1.

- [ ] **Step 1: Write failing schema contracts**

Assert both schema mirrors contain:

```sql
tenant_scope TEXT NOT NULL DEFAULT 'standalone'
CONSTRAINT ck_llm_remote_batch_jobs_tenant_scope
UNIQUE (tenant_scope, endpoint_alias, remote_batch_id)
ALTER TABLE llm_remote_batch_jobs ENABLE ROW LEVEL SECURITY
ALTER TABLE llm_remote_batch_jobs FORCE ROW LEVEL SECURITY
current_setting('pg_llm_batch.tenant_scope', true)
```

Assert the migration adds/backfills the column, drops `uq_llm_remote_batch_jobs_endpoint_id`, creates the tenant-qualified constraint only when absent, and never deletes lifecycle rows. Update the old schema test so it rejects the superseded two-column uniqueness contract. Preserve the exact packaged/deployable schema mirror test.

- [ ] **Step 2: Run focused schema tests and record RED**

```bash
pytest -q \
  tests/test_tenant_lifecycle_schema.py \
  tests/test_remote_batch_lifecycle.py::test_schema_defines_an_ordered_terminal_safe_remote_lifecycle_table \
  tests/test_schema_integrity.py
```

Expected: FAIL because tenant identity and policy are absent.

- [ ] **Step 3: Implement new-install and legacy migration SQL**

Add `tenant_scope` to the table definition. Immediately after table creation, add an idempotent migration that:

```sql
ALTER TABLE llm_remote_batch_jobs
    ADD COLUMN IF NOT EXISTS tenant_scope TEXT;

UPDATE llm_remote_batch_jobs
SET tenant_scope = 'standalone'
WHERE tenant_scope IS NULL;

ALTER TABLE llm_remote_batch_jobs
    ALTER COLUMN tenant_scope SET DEFAULT 'standalone',
    ALTER COLUMN tenant_scope SET NOT NULL;
```

Use a `DO $$ ... $$` block to add the named check constraint when absent, drop the superseded unique constraint when present, and add the tenant-qualified unique constraint when absent. Create the tenant/status/observation index. Within the same PostgreSQL statement, keep owner-enforcement relaxation, legacy backfill, constraint migration, RLS enable and force, policy recreation under default-deny, and forced-RLS restoration atomic. Enable and force RLS before recreating the package policy. Recreate the package policy idempotently under forced default-deny behavior with `DROP POLICY IF EXISTS` followed by `CREATE POLICY ... TO PUBLIC USING (...) WITH CHECK (...)`, then restore forced RLS before leaving the atomic statement.

- [ ] **Step 4: Synchronize the deployable schema mirror exactly**

Copy the complete canonical `pg_llm_batch/schema.sql` content to `docker/postgres/init/02_schema.sql`; do not patch the mirror independently.

- [ ] **Step 5: Run schema tests**

```bash
pytest -q tests/test_tenant_lifecycle_schema.py tests/test_schema_integrity.py tests/test_remote_batch_lifecycle.py
```

Expected: PASS.

- [ ] **Step 6: Commit the schema slice**

```bash
git add pg_llm_batch/schema.sql docker/postgres/init/02_schema.sql \
  tests/test_tenant_lifecycle_schema.py tests/test_schema_integrity.py \
  tests/test_remote_batch_lifecycle.py
git commit -m "feat(schema): isolate lifecycle rows by tenant"
```

### Task 3: Bind tenant scope transaction-locally for persistence and reads

**Files:**
- Modify: `pg_llm_batch/db.py`
- Modify: `tests/test_remote_batch_lifecycle.py`
- Create: `tests/test_tenant_lifecycle_persistence.py`

**Interfaces:**
- Produces: `_set_transaction_tenant_scope(cursor: Any, tenant_scope: str) -> None`, `persist_tenant_remote_batch_state(...) -> dict[str, Any]`, `get_tenant_remote_batch_state(...) -> dict[str, Any] | None`, and `get_remote_batch_state(...) -> dict[str, Any] | None`.
- Preserves: `persist_remote_batch_state(...)` positional and keyword signature.

- [ ] **Step 1: Write failing persistence tests**

Use deterministic psycopg doubles to assert:

1. `persist_remote_batch_state` executes `set_config` first with `standalone` and then tenant-qualified upsert SQL.
2. `persist_tenant_remote_batch_state` validates scope before `psycopg.connect`.
3. Two calls with identical alias/batch IDs and different tenants bind different first identity parameters.
4. The conflict target is `(tenant_scope, endpoint_alias, remote_batch_id)`.
5. Returned snapshots include the exact `tenant_scope`.
6. `get_tenant_remote_batch_state` validates all identity fields, sets scope first, binds all three identity values, and maps a deterministic row to public field names.
7. A missing row returns `None`; database failures are not converted to absence.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
pytest -q tests/test_tenant_lifecycle_persistence.py tests/test_remote_batch_lifecycle.py
```

Expected: FAIL because tenant persistence/read interfaces do not exist and the old SQL has a two-column conflict target.

- [ ] **Step 3: Refactor persistence behind one internal implementation**

Create an internal function with signature:

```python
def _persist_remote_batch_state(
    dsn: str,
    tenant_scope: str,
    endpoint_alias: str,
    provider_batch: Mapping[str, Any],
    observation_order: int,
    *,
    observed_at: Optional[datetime] = None,
) -> Dict[str, Any]:
```

Validate tenant scope first, include it in the snapshot and insert columns, and change the conflict target to the tenant-qualified identity. Inside the same connection/transaction execute:

```python
cur.execute(
    "SELECT set_config('pg_llm_batch.tenant_scope', %s, true)",
    (normalized_tenant_scope,),
)
cur.execute(sql, params)
```

`persist_remote_batch_state` delegates with `DEFAULT_TENANT_SCOPE`. The tenant entry point delegates with the explicit validated value.

- [ ] **Step 4: Add scoped reads**

Implement `get_tenant_remote_batch_state` with a parameterized SELECT for exactly one triple. Set transaction scope before the SELECT. Return a documented dictionary containing tenant, endpoint, remote IDs, order, file IDs, endpoint, status, counts, metadata, and timestamps. Add `get_remote_batch_state` as the standalone wrapper.

- [ ] **Step 5: Run focused tests and full non-integration suite**

```bash
pytest -q tests/test_tenant_lifecycle_persistence.py tests/test_remote_batch_lifecycle.py
pytest -q -m "not integration"
```

Expected: PASS.

- [ ] **Step 6: Commit the database API slice**

```bash
git add pg_llm_batch/db.py tests/test_tenant_lifecycle_persistence.py \
  tests/test_remote_batch_lifecycle.py
git commit -m "feat(tenant): persist and read scoped lifecycle state"
```

### Task 4: Add a required-scope tenant durable client

**Files:**
- Modify: `pg_llm_batch/durable_client.py`
- Modify: `pg_llm_batch/__init__.py`
- Create: `tests/test_tenant_durable_client.py`

**Interfaces:**
- Produces: `TenantLifecycleRecorder`, `TenantDurableBatchAPIClient`, and a protected asynchronous recorder-dispatch method used by both clients.
- Consumes: `validate_tenant_scope` and `persist_tenant_remote_batch_state` from Tasks 1 and 3.

- [ ] **Step 1: Write failing client tests**

Prove that:

- construction rejects an invalid scope synchronously;
- invalid scope causes zero reserver, credential, session, and provider calls;
- the exact scope is immutable on the client instance;
- create, status, and accepted cancellation pass `(dsn, tenant_scope, endpoint_alias, normalized_snapshot, observation_order)` to a tenant recorder;
- the existing durable client still calls a four-argument custom recorder and uses no tenant-aware signature;
- reservation and persistence recovery evidence include the trusted tenant scope for the tenant client but never provider metadata or bodies.

- [ ] **Step 2: Run the focused tests and capture RED**

```bash
pytest -q tests/test_tenant_durable_client.py
```

Expected: FAIL because the tenant client and recorder seam do not exist.

- [ ] **Step 3: Extract recorder dispatch without breaking the old seam**

In `DurableBatchAPIClient`, add:

```python
async def _record_lifecycle_snapshot(
    self,
    endpoint_alias: str,
    provider_batch: Mapping[str, Any],
    observation_order: int,
) -> None:
    """Dispatch one normalized snapshot through the configured recorder seam."""
```

The base implementation calls the existing four-argument recorder in
`asyncio.to_thread`. Update `_persist_snapshot` to call this method rather than
the recorder directly.

- [ ] **Step 4: Implement the tenant subclass**

The constructor requires keyword-only `tenant_scope: str`, validates it before
`super().__init__`, stores it in a read-only property, and accepts
`tenant_lifecycle_recorder` defaulting to `persist_tenant_remote_batch_state`.
Override `_record_lifecycle_snapshot` to call the five-argument tenant recorder.
Override the bounded recovery-data builder or relevant methods so tenant scope is
included without duplicating provider operation logic.

- [ ] **Step 5: Export the public interface and test**

Export `TenantDurableBatchAPIClient` from `pg_llm_batch.__init__`. Run:

```bash
pytest -q tests/test_tenant_durable_client.py tests/test_remote_batch_lifecycle.py
pytest -q -m "not integration"
ruff check pg_llm_batch tests
```

Expected: PASS.

- [ ] **Step 6: Commit the client slice**

```bash
git add pg_llm_batch/durable_client.py pg_llm_batch/__init__.py \
  tests/test_tenant_durable_client.py
git commit -m "feat(client): add tenant-scoped durable lifecycle"
```

### Task 5: Prove live migration, RLS isolation, and rollback behavior

**Files:**
- Create: `tests/test_tenant_lifecycle_integration.py`
- Modify: `tests/test_schema_integrity.py`

**Interfaces:**
- Consumes: `apply_schema`, tenant persistence/read helpers, and the PostgreSQL container contract.
- Produces: deterministic integration evidence that current and migrated schemas isolate rows.

- [ ] **Step 1: Write integration tests before relying on them**

Under `@pytest.mark.integration`, create a legacy `llm_remote_batch_jobs` shape without `tenant_scope`, insert one row, run `apply_schema`, and assert the row is backfilled to `standalone`, the new unique constraint exists, and applying schema again succeeds. In a clean transaction, persist the same `(endpoint_alias, remote_batch_id)` for tenants A and B and prove each scoped read returns only its own status/metadata. Execute a direct SELECT without setting the tenant GUC and assert zero rows are visible for the non-bypass test role.

- [ ] **Step 2: Run against the bundled PostgreSQL image**

```bash
docker compose up -d --build postgres
PG_LLM_BATCH_TEST_DSN=postgresql://pgllm:pgllm@localhost:5432/pgllm \
  pytest -q -m integration tests/test_tenant_lifecycle_integration.py
```

Expected before final schema implementation: FAIL on absent tenant column/policy. Expected after Tasks 2-4: PASS.

- [ ] **Step 3: Add deterministic rollback verification**

Within a transaction that sets tenant A, force a subsequent statement failure after a tentative lifecycle write and roll back. Assert no new tenant A row exists. Then reuse the same pooled connection with tenant B and prove transaction-local `set_config(..., true)` did not leak tenant A.

- [ ] **Step 4: Run integration and mirror tests**

```bash
PG_LLM_BATCH_TEST_DSN=postgresql://pgllm:pgllm@localhost:5432/pgllm \
  pytest -q -m integration tests/test_tenant_lifecycle_integration.py
pytest -q tests/test_schema_integrity.py
```

Expected: PASS.

- [ ] **Step 5: Commit integration evidence**

```bash
git add tests/test_tenant_lifecycle_integration.py tests/test_schema_integrity.py
git commit -m "test(tenant): prove lifecycle row isolation"
```

### Task 6: Publish authoritative operator and architecture contracts

**Files:**
- Create: `docs/doctoring/tenant-scoped-lifecycle.md`
- Create: `ARCHITECTURE.md`
- Create: `CLAUDE.md`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/remote-batch-lifecycle.md`
- Modify: `CHANGELOG.md`
- Create: `docs/superpowers/evidence/2026-08-05-tenant-scoped-lifecycle-red-green.md`

**Interfaces:**
- Documents: exact public constructors/functions, trusted-boundary ownership, migration order, RLS bypass limitations, pooled-connection safety, and MSA embedding.

- [ ] **Step 1: Write documentation contract tests where existing patterns support them**

Add static assertions to the relevant schema/API tests requiring the public tenant client, default standalone scope, RLS role warning, exact policy setting, and APA references. These tests must fail before documentation updates.

- [ ] **Step 2: Update user and operator documentation**

Add standalone and tenant examples:

```python
from pg_llm_batch import TenantDurableBatchAPIClient

async with TenantDurableBatchAPIClient(
    dsn,
    provider,
    tenant_scope=trusted_authorized_tenant,
) as client:
    status = await client.get_batch_status(batch_id, "default")
```

State that scope must come from the host authorization layer, never provider metadata. Document `NOSUPERUSER NOBYPASSRLS`, direct SQL transaction scoping, default-deny behavior, migration backfill, and rollback/pool isolation.

- [ ] **Step 3: Add architecture and agent decision records**

`ARCHITECTURE.md` describes standalone versus MSA boundaries and the lifecycle data flow. `CLAUDE.md` and `AGENTS.md` make the tenant contract, exact-head gates, no competing branch writers, database naming, 100% coverage, and NVIDIA/OpenCode scheduler rules authoritative for future agents.

- [ ] **Step 4: Record standards in APA 7th form**

Cite PostgreSQL 18 row security and configuration functions, OWASP Multi-Tenant Security Cheat Sheet, and NIST SP 800-53 Rev. 5 Release 5.2.0. Avoid claiming formal certification or isolation against superuser/BYPASSRLS roles.

- [ ] **Step 5: Record immutable RED/GREEN evidence and changelog**

The evidence document lists exact RED commit/run, exact GREEN head/run, focused tests, complete suite, coverage, package, container, security, and review outcomes. `CHANGELOG.md` remains under `Unreleased`; do not bump version in this feature PR.

- [ ] **Step 6: Commit documentation**

```bash
git add AGENTS.md CLAUDE.md ARCHITECTURE.md CHANGELOG.md README.md \
  docs/remote-batch-lifecycle.md docs/doctoring/tenant-scoped-lifecycle.md \
  docs/superpowers/evidence/2026-08-05-tenant-scoped-lifecycle-red-green.md
git commit -m "docs(tenant): define lifecycle isolation contract"
```

### Task 7: Run exact-head release-quality verification and open the PR

**Files:**
- Verify all changed production, test, schema, workflow, and documentation files.

**Interfaces:**
- Produces: one reviewable PR with exact head/base evidence and no temporary workflow.

- [ ] **Step 1: Run complete deterministic verification**

```bash
python -m compileall -q pg_llm_batch tests
ruff check pg_llm_batch tests
pytest -q -m "not integration"
interrogate --fail-under 100 pg_llm_batch
coverage run -m pytest -q -m "not integration"
coverage report --fail-under=100
uv lock --check
rm -rf dist
uv build --no-sources
docker compose config >/dev/null
docker build --tag pg-llm-batch:tenant-scope .
docker build --tag pg-llm-batch-postgres:tenant-scope docker/postgres
git diff --check
git status --short
```

Expected: all commands succeed; no generated artifact is tracked.

- [ ] **Step 2: Run live integration verification**

```bash
PG_LLM_BATCH_TEST_DSN=postgresql://pgllm:pgllm@localhost:5432/pgllm \
  pytest -q -m integration
```

Expected: PASS.

- [ ] **Step 3: Verify exact branch state**

Confirm the branch contains one implementation path, no one-shot/write-capable workflow, no `.coverage`, build product, or cache, and is based on the current `main`. Record exact head and base SHAs.

- [ ] **Step 4: Open a draft PR with RED/GREEN evidence**

The PR body names every public and database contract, exact current head/base, test and security evidence, migration/rollback behavior, RLS limitations, and the fact that release version remains unchanged.

- [ ] **Step 5: Review every automated and human finding**

Classify findings as valid, stale, duplicate, incorrect, infrastructure-only, rate-limited, or superseded. Implement valid findings one at a time with focused tests, resolve only addressed threads, and request exact-head CodeRabbit, OpenCode, Noema, and independent non-author review.

- [ ] **Step 6: Merge only after all exact-head gates pass**

Do not treat queued, pending, cancelled, skipped-required, absent, stale-head, or stale-base evidence as success. Merge only after branch protection, security gates, required checks, current-head automated reviews, and independent non-author approval are all satisfied.
