# Result application semantic identifiers

## Decision

The Result Application bounded context owns checkpointed provider-record application inside a caller-supplied transaction. Organization-owned implementation names use semantic multiword vocabulary. Historical public Python names remain only at an explicit compatibility boundary when changing them would break released callers.

## Old → new vocabulary

- `ResultApplicationError.phase` constructor argument → `application_phase`; the serialized diagnostic key `details["phase"]` remains stable.
- `ResultApplicationOutcome.applied` field → `record_applied`; read-only `applied` remains a compatibility property.
- `ResultApplicationOutcome.checkpoint` field → `result_checkpoint`; read-only `checkpoint` remains a compatibility property.
- private validation `field` / `reason` → `field_name` / `validation_reason`.
- private `item` / `apply_record` → `checkpointed_record` / `record_effect`.
- implementation `cursor` → `transaction_cursor`, `candidate` → `validated_record`, `previous` → `previous_checkpoint`, and phase-specific failure/result locals use semantic multiword names.

The released function `apply_checkpointed_result_in_transaction(cursor, checkpoint_store, consumer_name, item, apply_record)` keeps its historical keyword signature as an anti-corruption adapter. It immediately translates those names into `_apply_checkpointed_record_in_transaction(transaction_cursor, checkpoint_store, consumer_name, checkpointed_record, record_effect)`. This preserves external source compatibility without allowing generic vocabulary to remain authoritative inside the package.

## DDD boundary and invariants

**Bounded Context:** Result Application. **Aggregate interaction:** one checkpointed provider result plus its durable checkpoint advancement. **Domain service:** transactional result application. **Value objects:** `BatchResultCheckpoint` and `CheckpointedBatchResultRecord`. **Invariant:** the local effect and checkpoint save execute in the same caller-owned transaction; exact replay does not reapply the effect; checkpoint regression fails closed; asynchronous/deferred work cannot retain the scoped cursor capability.

The naming repair changes no provider protocol, PostgreSQL schema, transaction ownership, retry behavior, authorization boundary, or checkpoint ordering semantics.

## Compatibility and persistence

There is no database migration, FK/index/constraint change, UPSERT change, partitioning change, lock change, or read/write-topology change. Existing callers may continue to construct `ResultApplicationOutcome(applied=..., checkpoint=...)`, read `.applied` / `.checkpoint`, and call `apply_checkpointed_result_in_transaction` with historical keyword arguments. New package-owned code uses `record_applied`, `result_checkpoint`, `transaction_cursor`, `checkpointed_record`, and `record_effect`.

## TDD evidence

The RED-first commit `6e10a87cf8c0f090854672a7453cf20fb2d416e9` adds `tests/test_result_application_naming_contract.py`. Against its exact predecessor production source, the semantic helper signatures, semantic outcome fields, compatibility properties, and semantic core function did not exist. Production repair follows in ordinary non-force history.

Fresh exact-head repository checks remain authoritative. Predecessor/base check results do not transfer.

## Rollback

The code-only repair can be reverted without data migration because neither stored checkpoint rows nor provider/wire payloads change. A rollback restores the prior Python-internal naming while leaving persisted state untouched.
