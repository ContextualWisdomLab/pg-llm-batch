# Result application semantic identifiers

## Decision

The Result Application bounded context owns checkpointed provider-record application inside a caller-supplied transaction. Organization-owned implementation names use semantic multiword vocabulary. Historical public Python names remain only at explicit compatibility boundaries when changing them would break released callers, including Python dataclass field/introspection shape.

## Old → new vocabulary

- `ResultApplicationError.phase` constructor argument → `application_phase`; the serialized diagnostic key `details["phase"]` remains stable.
- Internal result state now uses `_SemanticResultApplicationOutcome.record_applied` and `.result_checkpoint`.
- Public `ResultApplicationOutcome.applied` and `.checkpoint` remain the released dataclass fields so constructor keywords, `dataclasses.fields`, and `dataclasses.asdict` retain their historical shape; new semantic read properties `.record_applied` and `.result_checkpoint` are additive.
- private validation `field` / `reason` → `field_name` / `validation_reason`.
- private `item` / `apply_record` → `checkpointed_record` / `record_effect`.
- implementation `cursor` → `transaction_cursor`, `candidate` → `validated_record`, `previous` → `previous_checkpoint`, and phase-specific failure/result locals use semantic multiword names.
- `_ResultApplicationCursor` now owns `transaction_cursor`, `capability_active`, and `revoke_cursor_capability` vocabulary internally while DB-API method names such as `execute`, `executemany`, and `fetchone` remain adapter protocol names.

The released function `apply_checkpointed_result_in_transaction(cursor, checkpoint_store, consumer_name, item, apply_record)` keeps its historical keyword signature as an anti-corruption adapter. It immediately translates those names into `_apply_checkpointed_record_in_transaction(transaction_cursor, checkpoint_store, consumer_name, checkpointed_record, record_effect)` and converts the semantic internal outcome back to the stable public dataclass. This preserves external source and dataclass-serialization compatibility without allowing generic vocabulary to remain authoritative inside the package.

## DDD boundary and invariants

**Bounded Context:** Result Application. **Aggregate interaction:** one checkpointed provider result plus its durable checkpoint advancement. **Domain service:** transactional result application. **Value objects:** `BatchResultCheckpoint` and `CheckpointedBatchResultRecord`. **Invariant:** the local effect and checkpoint save execute in the same caller-owned transaction; exact replay does not reapply the effect; checkpoint regression fails closed; asynchronous/deferred work cannot retain the scoped cursor capability.

The naming repair changes no provider protocol, PostgreSQL schema, transaction ownership, retry behavior, authorization boundary, or checkpoint ordering semantics.

## Compatibility and persistence

There is no database migration, FK/index/constraint change, UPSERT change, partitioning change, lock change, or read/write-topology change. Existing callers may continue to construct `ResultApplicationOutcome(applied=..., checkpoint=...)`, inspect/serialize those dataclass fields, read `.applied` / `.checkpoint`, and call `apply_checkpointed_result_in_transaction` with historical keyword arguments. Additive semantic public reads `.record_applied` / `.result_checkpoint` and the private semantic core provide the new ubiquitous language without silently changing released shape.

## TDD evidence

The RED-first commit `6e10a87cf8c0f090854672a7453cf20fb2d416e9` established semantic internal signatures. A later compatibility review identified that making the public dataclass fields semantic would change `dataclasses.fields`/`dataclasses.asdict`; RED commit `cefc0c3723a4f093fb8181bae0c596a1796f7668` therefore pinned the released dataclass shape plus a private semantic outcome model before production repair in `b58c11f0f263b3d1d4141b37acaed8430101c8a9`.

Fresh exact-head repository checks remain authoritative. Predecessor/base check results do not transfer.

## Rollback

The code-only repair can be reverted without data migration because neither stored checkpoint rows nor provider/wire payloads change. A rollback restores the prior Python-internal naming while leaving persisted state untouched.
