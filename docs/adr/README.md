# Architecture Decision Record index

## Authority and status

This index is the canonical entry point for durable pg-llm-batch architecture/governance decisions. A file present only on an open PR is **ACTIVE-PR documentation** and does not become protected-main documentation authority until merged. A decision recorded by that file may nevertheless describe behavior already **IMPLEMENTED-ON-PROTECTED-MAIN**; document-integration maturity and implementation maturity are separate. Feature-specific ADRs carried by other active PRs retain their own status and must not be presented as shipped behavior here.

## Foundational protected-main product decisions

The following records capture architectural choices already implemented on protected main. The decisions are `IMPLEMENTED-ON-PROTECTED-MAIN`; these newly written records themselves remain ACTIVE-PR #93 until this documentation branch integrates.

| ADR | Decision | Implementation maturity |
| --- | --- | --- |
| [`foundation-postgresql-authority.md`](foundation-postgresql-authority.md) | PostgreSQL is the package-owned durable authority for current configuration, batch/request/payload state, endpoint mapping, and lifecycle projection; batch payload reconstruction remains disk-free | IMPLEMENTED-ON-PROTECTED-MAIN |
| [`foundation-provider-http-boundary.md`](foundation-provider-http-boundary.md) | Provider HTTP is external/untrusted; validate destinations/identifiers, bound responses/time, and keep side-effecting POST operations single-attempt unless a reviewed idempotency contract changes that rule | IMPLEMENTED-ON-PROTECTED-MAIN |
| [`foundation-standalone-composition.md`](foundation-standalone-composition.md) | Preserve both standalone operation and embedding-host composition without mandatory sibling-service or hidden cross-service database coupling | IMPLEMENTED-ON-PROTECTED-MAIN |
| [`foundation-lifecycle-observation.md`](foundation-lifecycle-observation.md) | Reserve database-owned observation order before durable lifecycle provider I/O and surface provider-success/persistence-failure as reconciliation evidence | IMPLEMENTED-ON-PROTECTED-MAIN |

## Canonical governance ADRs

| ADR | Decision | Maturity |
| --- | --- | --- |
| [`docs/automation/ADR-0001-work-conserving-maintenance.md`](../automation/ADR-0001-work-conserving-maintenance.md) | Autonomous maintenance is work-conserving; one successful action or local wait is not invocation completion | ACTIVE-PR (#93) |
| [`docs/automation/ADR-0002-evidence-identity-and-writer-lease.md`](../automation/ADR-0002-evidence-identity-and-writer-lease.md) | Separate source/base/check/review authorities and enforce branch-local writer leases | ACTIVE-PR (#93) |
| [`docs/automation/ADR-0003-canonical-documentation-authority.md`](../automation/ADR-0003-canonical-documentation-authority.md) | Keep one source-bound documentation graph with explicit fitness/maturity and machine-checkable drift controls | ACTIVE-PR (#93) |
| [`docs/automation/ADR-0004-review-evidence-separation.md`](../automation/ADR-0004-review-evidence-separation.md) | Keep infrastructure/policy blockers separate from semantic source findings; unavailable semantic review abstains rather than synthesizing code defects | ACTIVE-PR (#93) |
| [`docs/automation/ADR-0005-protected-main-operational-acceptance.md`](../automation/ADR-0005-protected-main-operational-acceptance.md) | Source merge is intermediate; require capability-specific protected-main operational acceptance before incident/release closure where applicable | ACTIVE-PR (#93) |
| [`docs/automation/ADR-0006-scheduler-failure-recovery.md`](../automation/ADR-0006-scheduler-failure-recovery.md) | Treat generic scheduler failures as control-plane incidents, preserve one authoritative hourly task, compact control prompts when needed, and resume repository work in the same invocation | ACTIVE-PR (#93) |

## Feature decisions carried by active implementation PRs

The following decisions are indexed by capability rather than promoted to protected-main status. Exact filenames/status must be revalidated on the live implementing branch before merge:

- tenant-qualified durable lifecycle / PostgreSQL RLS — #53;
- descriptor-pinned reproducible release evidence — #57;
- incremental result streaming and response ownership — #58;
- prefix-bound resumable result checkpoints — #59;
- durable checkpoint CAS persistence and rollback boundary — #60;
- repository-local maintenance credential/writer boundary — #69;
- health/readiness disclosure and resource bounds — #70;
- bounded retry/TLS/response-handoff classification — #71;
- checkpoint OpenTelemetry observability — current replacement #92; SUPERSEDED #78;
- append-only checkpoint acceptance audit — current replacement #94; SUPERSEDED #79;
- atomic checkpoint migration operator — current replacement #95; SUPERSEDED #80;
- bounded checkpoint-audit pagination — current replacement #96; SUPERSEDED #83;
- snapshot-manifest assurance — current replacement #97 on #96; SUPERSEDED #84 is closed unmerged and its checks/reviews do not transfer;
- secret input outside process argv — #85;
- typed config/cached mutable-state authority — #86;
- PostgreSQL connection ownership and cleanup — #87;
- exact source-head CI evidence — #88;
- explicit bootstrap-source precedence — #89;
- loopback-only standalone Compose publication — #91;
- fail-closed retirement of the legacy direct-SQL `pg_cron` + `pgsql-http` provider path while preserving historical retrieval evidence and keeping provider network/credential authority in the validated Python client — #101.

Issue #90 is a planned operator-facing cancellation slice, not an accepted/shipped ADR. It is intentionally deferred while overlapping CLI/resource-ownership PRs remain active.

Issue #102 is planned bounded automatic provider reconciliation after #101; it must use validated provider remote batch identity and the Python provider boundary rather than recreate direct-SQL provider networking. Issue #103 is the separate planned existing-volume migration needed before removing legacy `pg_cron`/`http` image packages, preload, and extension configuration. Its canonical design is [`legacy-postgresql-extension-retirement.md`](legacy-postgresql-extension-retirement.md). Neither issue is accepted/shipped behavior or a reason to invent new persistence in the ERD.

## ADR content contract

A material ADR should contain:

1. status/maturity;
2. context and decision drivers;
3. considered alternatives;
4. decision;
5. consequences and explicit non-goals;
6. failure/recovery behavior;
7. security/privacy/governance impact;
8. compatibility/migration implications;
9. verification/acceptance evidence required;
10. rollback and supersession conditions.

Transient run IDs and mutable PR-head SHAs belong in dated evidence or PR descriptions rather than timeless decision text unless a historical incident is essential to the rationale.

## Supersession rules

A newer ADR may supersede an older decision only when it names the predecessor and explains what changed. Closing or replacing an implementation PR does not automatically invalidate the underlying accepted design; however, the index must point to the current implementation owner and must never leave a closed PR labelled ACTIVE-PR indefinitely.
