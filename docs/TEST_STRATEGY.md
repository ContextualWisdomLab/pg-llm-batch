# Test strategy

## Quality objective

pg-llm-batch must prove behavior at the boundary where failures matter: PostgreSQL transactions and migrations, provider HTTP acquisition/streaming, configuration and secret authority, deterministic batch construction, CLI/operator behavior, package/release artifacts, and GitHub evidence identity. Coverage percentage is necessary but never substitutes for realistic assertions.

## Evidence classes

1. **Unit and contract tests** — deterministic logic, validation, serialization, bounds, state machines, documentation contracts.
2. **PostgreSQL integration tests** — schema/migration, transaction ownership, concurrency, RLS, rollback, durable lifecycle/checkpoint/audit semantics.
3. **HTTP/provider tests** — destination validation, retry classification, bounded response processing, response ownership, confidentiality and no-replay behavior.
4. **Packaging and reproducibility tests** — wheel/sdist build, install/import, lock freshness, container build, artifact identity/provenance when implemented.
5. **Security analysis** — SAST, dependency/security scanners, secret scanning and specific exploit regressions.
6. **Review evidence** — semantic source review is distinct from test or infrastructure evidence.
7. **Operational acceptance** — protected-main execution for changes whose correctness depends on runtime/scheduler/deployment behavior.

## Required development cycle

For behavior changes use RED → GREEN → refactor:

- write the smallest realistic regression at the intended production boundary;
- run it and confirm it fails for the expected missing/incorrect behavior rather than setup, import, fixture or network noise;
- implement the narrowest root-cause fix;
- rerun the focused regression to GREEN;
- run the complete relevant suite and required repository gates;
- revalidate the exact contributor head and live base before merging.

A test added after implementation without observed RED evidence is useful regression coverage but is not equivalent TDD evidence.

## Protected-main baseline gates

Protected main currently encodes Python-version CI, Ruff/static quality, production statement/branch coverage, public docstring coverage, lock/package checks, Compose/container validation, SAST and security workflows. Exact names and commands live in `.github/workflows/ci.yml`, project configuration and workflow files; this document describes intent rather than duplicating mutable YAML.

The acquisition target is exact 100% owned production statement and branch coverage plus complete beginner-readable public docstrings where the repository's tooling exposes those metrics. Exclusions must be narrow, reviewed and justified; generated artifacts, tests and external dependencies do not become production code merely to manipulate the metric.

## Domain-specific test matrix

| Surface | Minimum realistic evidence |
| --- | --- |
| `pg_llm_batch/orchestrator.py` | deterministic batch partitioning, token limits, PostgreSQL ownership/cleanup, failure rollback |
| `pg_llm_batch/batch_api_client.py` | governed URL/resource IDs, bounded control/file bodies, retry/no-replay, provider error confidentiality, timeout/close behavior |
| `pg_llm_batch/durable_client.py` | monotonic observation ordering, remote identity reconciliation, persistence idempotency, malformed metadata rejection |
| `pg_llm_batch/schema.sql` | clean install, migration compatibility, constraints/indexes/FKs, no silent orphan repair |
| `pg_llm_batch/health.py` | readiness truth, malformed evidence fail-closed, bounded database work; ACTIVE-PR hardening must test concurrency/listener/redaction |
| configuration/secrets | type normalization, explicit-vs-ambient authority, secret confidentiality, constructor/close ownership |
| checkpoint/audit ACTIVE-PR chain | prefix integrity, CAS concurrency, RLS, migration/rollback, append-only audit, bounded export/snapshot invariants |
| release ACTIVE-PR #57 | clean-source double build, byte identity, descriptor/path race resistance, bounded hashing and manifest handling |
| documentation | required graph, closed maturity vocabulary, Mermaid/code-fence presence, live source/schema names and active-vs-shipped discipline |

## Failure injection

Tests should deliberately exercise partial reads, zero-progress streams, malformed/non-byte chunks, oversized responses, timeouts, cancellation, provider status errors, TLS/identity failures, transaction conflicts, duplicate submissions, stale checkpoints, wrong tenant context, concurrent writers, connection-construction failure, cleanup failure, rollback refusal, filesystem race/symlink/hard-link cases where release code touches disk, and stale/missing CI evidence.

Mocks are acceptable only when the real dependency cannot be safely invoked in the test layer; tests must still assert package-visible behavior rather than mock call counts alone. Live PostgreSQL behavior should use an actual compatible PostgreSQL service/container when semantics depend on transactions, constraints, isolation or RLS.

## Evidence identity

A successful check is valid only for the commit it actually exercised. The repository distinguishes:

- exact contributor head;
- PR base snapshot metadata;
- independently resolved live base-ref tip;
- synthetic merge commit;
- workflow run/job execution identity;
- semantic review submission and reviewed commit.

ACTIVE-PR #88 makes exact source-head checkout/verification explicit in CI. Until integrated, older workflows must not be retroactively described as protected exact-source governance.

## Merge and release acceptance

Merge requires every live required gate to be terminal-success on the unchanged eligible head, zero valid unresolved findings, and qualifying independent non-author formal approval where live policy/governance requires it. Queued, pending, cancelled, skipped-required, absent, neutral-required, stale, predecessor, synthetic-only, status-only, author-only or rate-limited evidence is not success.

Release adds package/install reproducibility, SBOM/provenance, migration/rollback/recovery, compatibility and operator acceptance appropriate to the changed scope. A green feature branch or complete documentation pack alone is not release readiness.
