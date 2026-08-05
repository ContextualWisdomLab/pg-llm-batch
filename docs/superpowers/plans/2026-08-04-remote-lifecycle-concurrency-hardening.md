# Durable Remote Lifecycle Concurrency Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PR #50's durable lifecycle store genuinely overlap-safe across workers, terminal-state-safe, and bounded at the metadata trust boundary.

**Architecture:** Reserve a PostgreSQL sequence order before each durable provider request, persist that order with the curated observation, accept only strictly newer orders, protect terminal status identity, and canonicalize provider metadata within a 64 KiB limit.

**Tech Stack:** Python 3.10+, asyncio, psycopg 3, PostgreSQL sequence and `INSERT ... ON CONFLICT`, pytest, pytest-asyncio, pytest-cov, Ruff, Interrogate.

## Global constraints

- Durable requests reserve global order before provider I/O.
- Reservation failure prevents remote side effects.
- Earlier orders never overwrite later orders.
- Stored terminal status may only be enriched by the same terminal status.
- Metadata is canonical JSON, finite, serializable, and at most 64 KiB UTF-8.
- Base `BatchAPIClient` remains unchanged.
- Side-effecting POST operations remain single-attempt.
- All database objects use descriptive multi-word `snake_case`.
- Production statement, branch, and docstring coverage remain 100%.
- Python 3.10, 3.12, and 3.14 remain supported.

---

### Task 1: Define the failing concurrency and trust-boundary contract

**Files:**
- Modify: `tests/test_remote_batch_lifecycle.py`
- Create temporarily: `.github/workflows/one-shot-lifecycle-hardening-red.yml`
- Create after execution: `docs/superpowers/evidence/2026-08-04-remote-lifecycle-hardening-red.md`

- [x] Add a source/schema test requiring `llm_remote_batch_observation_sequence`, `observation_order`, strict greater-than update ordering, and terminal-status equality protection.
- [x] Add a client test requiring an `observation_reserver` seam and verifying reservation occurs before provider request entry.
- [x] Add a reservation-failure test requiring zero provider calls and structured `phase: reservation` evidence.
- [x] Update the persistence-failure test to require `phase: persistence` and `observation_order`.
- [x] Add metadata tests for sets, cycles, NaN, invalid Unicode, and payloads beyond 64 KiB, all normalized to `{}`.
- [x] Run only the new tests against the original implementation and require the intended failures before recording red evidence.
- [x] Remove the temporary red workflow in the same evidence commit.

### Task 2: Add database-owned observation ordering

**Files:**
- Modify: `pg_llm_batch/schema.sql`
- Modify: `pg_llm_batch/db.py`
- Test: `tests/test_remote_batch_lifecycle.py`

- [x] Add `llm_remote_batch_observation_sequence` as a positive, non-cycling BIGINT sequence.
- [x] Add `observation_order BIGINT NOT NULL CHECK (observation_order > 0)` to `llm_remote_batch_jobs`.
- [x] Implement `reserve_remote_batch_observation_order(dsn) -> int` with result validation.
- [x] Require a positive non-boolean `observation_order` in `persist_remote_batch_state`.
- [x] Insert and update the order and accept only `EXCLUDED.observation_order > stored.observation_order`.
- [x] When stored state is terminal, accept only an identical terminal status.

### Task 3: Harden the durable client and metadata boundary

**Files:**
- Modify: `pg_llm_batch/durable_client.py`
- Modify: `pg_llm_batch/db.py`
- Test: `tests/test_remote_batch_lifecycle.py`

- [x] Add injectable `ObservationReserver` and four-argument `LifecycleRecorder` seams.
- [x] Reserve an order before create, poll, and cancellation provider calls.
- [x] Raise structured reservation errors before provider I/O.
- [x] Pass the order to persistence and include phase/order in post-success failures.
- [x] Canonicalize metadata with `allow_nan=False` and normalize serialization failures to `{}`.
- [x] Enforce `MAX_PROVIDER_METADATA_BYTES = 64 * 1024` against canonical UTF-8 bytes.
- [x] Verify overlapping request completion cannot regress a fake order-aware store.

### Task 4: Reconcile current main and documentation

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/remote-batch-lifecycle.md`
- Modify: `docs/superpowers/specs/2026-08-04-remote-lifecycle-concurrency-hardening-design.md`

- [x] Preserve all current `main` changelog entries, including PEP 639 metadata migration.
- [x] Document sequence reservation cost and guarantees, terminal enrichment, metadata limits, and failure phases.
- [x] Correct living OpenAI documentation citation to APA 7th undated/retrieval-date form.
- [x] Record exact local-equivalent verification evidence without pre-claiming hosted success.
- [x] Synchronize the branch with the current `main` head and remove the temporary synchronization workflow.

### Task 5: Verify, review, and merge

- [x] Run focused lifecycle tests: `45 passed`.
- [x] Run the complete non-integration suite: `283 passed, 3 deselected`.
- [x] Run compile, Ruff, Interrogate, 100% statement/branch coverage (`1273/1273` statements and `352/352` branches), lock, package, Compose, and both container builds.
- [x] Inspect the exact implementation patch for unrelated files and remove temporary workflows.
- [ ] Inspect exact-head human, CodeRabbit, security, and inline feedback; fix every valid current-head finding.
- [ ] Require exact-head CI, SAST Semgrep, and Security Scan success.
- [ ] Merge with exact head binding and re-query the open PR queue.
