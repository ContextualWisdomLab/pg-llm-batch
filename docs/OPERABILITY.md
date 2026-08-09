# Operability and recovery

## Scope

This document defines the operator contract for standalone pg-llm-batch and for hosts that embed it as a modular service. It does not invent an SLO, RPO, RTO, managed-service topology, or certification claim. Deployment-specific objectives must be measured and owned by the deployment.

## Runtime dependencies

Protected-main operation requires:

- PostgreSQL with the extensions and schema described by the project deployment artifacts;
- package configuration and secret storage in PostgreSQL according to current bootstrap rules;
- network access to explicitly configured OpenAI-compatible provider endpoints when remote batch operations are used;
- application identities with only the privileges needed for the selected operations;
- package/runtime versions accepted by repository CI and packaging metadata.

Optional CWL integrations remain external dependencies. Failure of a sibling service must not make standalone local database/token/batch operations impossible unless the caller selected a feature that explicitly depends on that service.

## Readiness and liveness

`/healthz` and `pg_llm_batch_health_check()` provide component readiness evidence. Operators must distinguish:

- process/network liveness;
- database connectivity;
- required PostgreSQL extension/schema readiness;
- provider reachability, which is not implied by database health;
- GitHub CI/review health, which is development-control evidence rather than application runtime readiness.

ACTIVE-PR #70/#91 harden public readiness disclosure, bounded request handling and listener exposure; until merged, those changes are not protected-main guarantees.

## Startup checks

Before serving or executing remote operations:

1. verify the intended PostgreSQL DSN and database identity;
2. verify required schema/migrations are installed and package/container schema mirrors agree;
3. verify required extensions and application privileges;
4. verify provider aliases/base URLs and corresponding secret entries where remote operations are enabled;
5. run the package self-check/readiness path appropriate to the deployment;
6. record the exact package/source version and migration state used for incident traceability.

Do not silently fall back to another database, provider, credential source, or tenant when an explicit target is malformed or unavailable.

## Normal operating flows

### Batch preparation

Read queued requests → count tokens → partition requests into bounded payloads → persist payload document → persist batch file → persist JSONL lines → assign queued requests → update batch totals → commit the preparation transaction. Token counting and partitioning occur before `_persist_payloads()` opens its persistence transaction. Inside that transaction, payload documents precede batch-file rows, JSONL rows precede request assignment, and batch totals are updated last. Any failure before commit rolls back the transaction, so those writes from the failed preparation invocation do not become durable partial state. Existing previously committed preparation state remains independently durable and is re-read under the idempotency rules. Operators should monitor failure counts, queue/batch state and database resource pressure; payloads are application data and should not be copied wholesale into logs.

### Remote batch lifecycle

Submit/poll/retrieve through governed provider configuration. Durable remote lifecycle state records curated identifiers/status/metadata in PostgreSQL. A local persisted state is evidence of what the package accepted, not proof that the provider will remain immutable.

### Result retrieval

Protected main supports bounded provider-file download. ACTIVE-PR #58/#59/#60 add incremental records, prefix checkpoints and durable checkpoint state. Operators must not rely on those recovery semantics until they are protected-main integrated.

## Failure classes and operator response

| Failure | Expected response |
| --- | --- |
| Invalid configuration/identifier | Fail closed; correct configuration; do not retry blindly |
| PostgreSQL unavailable | Stop dependent operation; restore DB connectivity; verify transaction/migration state before retry |
| Provider transient GET acquisition failure | Allow only the bounded reviewed retry policy; respect Retry-After within configured limits |
| Provider permanent/TLS/identity failure | Do not loop; correct trust/configuration boundary |
| Provider response/body failure after handoff | Do not replay already handed-off response work unless the specific API contract proves replay safety |
| Migration failure | Preserve failure evidence; rollback only with the reviewed rollback path; never delete durable evidence to make a migration pass |
| Checkpoint/audit conflict (ACTIVE-PR) | Re-read durable state, preserve tenant/consumer identity, use CAS/append-only rules; do not force overwrite |
| CI/review infrastructure failure | Keep source and infrastructure findings separate; repair the owning control plane or wait locally while advancing unrelated work |

## Logging, telemetry and privacy

Logs and telemetry should carry bounded low-cardinality operational facts: operation class, success/failure category, timing, counts, and stable non-sensitive identifiers where necessary. They should not contain API keys, raw secret values, full provider payloads, arbitrary exception text from untrusted dependencies, or sensitive prompts/responses by default. Optional OpenTelemetry is an observer, not an authority; telemetry failure must not corrupt application semantics.

## Backup and restore

The deployment owns PostgreSQL backup, encryption, retention, regional policy and restore testing. Restores must preserve referential integrity, migration ordering and durable lifecycle/checkpoint/audit evidence. Before resuming remote operations after restore, operators must reconcile provider state rather than assuming the provider rolled back with the database.

## Migration and rollback

Every package-owned schema change requires:

- ordered forward migration;
- explicit rollback or recovery semantics;
- live PostgreSQL regression evidence when semantics depend on PostgreSQL behavior;
- concurrency/idempotency treatment;
- refusal to destroy non-empty durable evidence unless an explicit reviewed destructive procedure exists;
- post-migration schema/behavior verification.

ACTIVE-PR #95 is the current linearized atomic checkpoint migration operator replacement; #80 is SUPERSEDED and is not current protected-main operator behavior.

## Incident evidence

Capture exact source/package version, database migration state, affected command/API path, bounded error category, exact provider endpoint alias (not secret), workflow/run identity when the incident is CI-related, and whether evidence came from protected main or an active PR. Avoid storing transient run IDs in timeless architecture documents; incident records may be dated.

## Release and rollback operations

Release only from an exact protected integrated head satisfying required CI/security/coverage/docstrings/package/provenance/review/migration/operational gates. ACTIVE-PR #57 adds stronger reproducible descriptor-pinned release evidence. If a release must be rolled back, use a known published artifact and compatible schema state; do not move a protected branch or mutate an old artifact to simulate rollback.

## Escalation boundaries

User/operator intervention is genuinely required when credentials/permissions are unavailable, destructive data-loss decisions cannot be inferred safely, an external independent approval is the sole remaining governance gate, or a product/security choice has irreconcilable trade-offs. A queued check, one blocked PR, or one unavailable provider is not a repository-wide stop condition.
