# Product–technical gap baseline

## Product responsibility

`ContextualWisdomLab/pg-llm-batch` is the independently deployable/embeddable PostgreSQL LLM batch foundation. It owns PostgreSQL configuration and encrypted-secret persistence, database token-count/batch execution support, provider batch HTTP integration, bounded JSONL result streaming, durable lifecycle/checkpoint evidence, and package-level recovery/release evidence. Host products retain their own authentication, authorization, tenant selection, buyer workflow, and domain truth.

## Bounded-context map

- **Provider Batch Gateway:** `BatchAPIClient` and provider HTTP/file operations. External provider identifiers and payload keys remain provider contracts and are validated/translated at the adapter boundary.
- **Durable Batch Lifecycle:** tenant-scoped lifecycle persistence with business identity `(tenant_scope, endpoint_alias, remote_batch_id)`, forced PostgreSQL RLS, and standalone compatibility.
- **Result Streaming:** bounded provider JSONL decoding and resumable `BatchResultCheckpoint` evidence.
- **Result Application:** atomically applies a `CheckpointedBatchResultRecord` effect and advances its durable checkpoint in a caller-owned transaction. Semantic internal vocabulary is `transaction_cursor`, `checkpointed_record`, `record_effect`, `record_applied`, and `result_checkpoint`; historical released Python names are compatibility adapters only.
- **Recovery / Release Evidence:** descriptor-bound backup/restore and reproducible release evidence without transferring provider or database content into diagnostics.

## DDD vocabulary and invariants

**Aggregates / entities:** durable remote batch lifecycle row, checkpoint consumer state. **Value objects:** `BatchResultCheckpoint`, `CheckpointedBatchResultRecord`, result-application outcome. **Domain services:** provider batch gateway, checkpoint store, result application, backup/restore verification. **Domain events/evidence:** lifecycle observations and content-free recovery/release evidence.

Key invariants are tenant context before persistence/provider work; forced RLS for ordinary application roles; exact checkpoint monotonicity; same-transaction local effect plus checkpoint advance; bounded provider decoding; fail-closed malformed provider/state evidence; no arbitrary SQL as an authorization substitute; and no generic provider payload field becoming internal domain authority without validation/translation.

## Naming-contract status

Current naming repair owner: branch `fix/result-application-semantic-identifiers`, based on protected `main@b84f0c94154043a3473939c01bb6471de5a129ae`.

The Result Application slice translates ambiguous package-owned names into semantic multiword vocabulary while keeping historical released names only at a documented compatibility boundary. RED-first evidence is commit `6e10a87cf8c0f090854672a7453cf20fb2d416e9`; production repair begins at `6e12edbe7e320ae4d3396837d4b3517808f2c2bc`. Fresh exact-head CI after all documentation commits is required before merge; predecessor evidence does not transfer.

No database object changes occur in this slice, so there is no migration, FK/index/constraint, UPSERT, 3NF, partition, locking, or read/write-topology change. Persisted checkpoint data and provider wire contracts remain unchanged.

## Current product / technical gaps

1. **Naming conformance:** continue repository-wide review of package-owned result-streaming, release-evidence, persistence, workflow, tests, and documentation identifiers. Prioritize public/persisted/shared contracts and preserve vendor/protocol names at adapters.
2. **Verification:** every source or contract repair requires exact-head tests, 100% required statement/branch/public-doc coverage, security checks, and current independent review under ordinary protection.
3. **Release evidence:** source versions and green development checks are not immutable release evidence; product claims must remain tied to actual release artifacts and reproducibility/provenance evidence.
4. **Consumer integration:** downstream hosts such as `contextual-orchestrator` and `naruon` consume released package contracts and provide authenticated tenant context; they must not copy package source or read package persistence as a cross-service shortcut.

## Security / operability baseline

The current architecture requires bounded provider response processing, exact tenant validation, parameterized transaction-local tenant context, forced RLS, non-superuser/non-`BYPASSRLS` application roles, controlled retries for idempotent GET operations only, redacted diagnostics, deterministic checkpoint conflict behavior, and descriptor-bound recovery/release evidence. Changes to these boundaries require dedicated regressions and doctoring rather than being hidden inside naming refactors.

## Evidence status

This baseline records repository truth visible on the current naming branch. It does not claim fresh exact-head workflow success, independent approval, release publication, buyer deployment, or downstream consumer validation until those artifacts exist on the unchanged final head.
