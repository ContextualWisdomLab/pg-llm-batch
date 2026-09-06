# ADR 0026: Lifecycle Outbox CHECK-Semantics Authority

- Status: Proposed
- Date: 2026-09-06
- Owners: pg-llm-batch

## Context

`public.llm_context_lifecycle_outbox` is the pg-llm-batch durability boundary for tenant-scoped lifecycle publication intent. Migration 0008 converges the package-owned payload, valid-time, and system-time CHECKs by comparing live PostgreSQL parser output with same-runtime temporary probe expressions. Migration 0009 is the final row-admission gate after that convergence.

Fresh review found that migration 0009 admitted the three CHECKs by name plus `convalidated` and inheritance flags, without re-reading their Boolean expressions. That creates a restore/operator-drift gap when migration 0008 has already been recorded as applied: an operator can drop one canonical CHECK and recreate a stricter or otherwise different expression under the same canonical name. PostgreSQL stores a CHECK expression in `pg_constraint.conbin`; the name is not semantic identity, and PostgreSQL explicitly documents that constraint names are not necessarily unique. A changed CHECK can reject an otherwise canonical insert or update.

The active container target remains PostgreSQL 16. PostgreSQL 18 documentation is used as the latest primary catalog/interface reference for the `pg_constraint` and `pg_get_expr` semantics exercised by the PostgreSQL 16 container contract.

## Decision

Migration 0009 independently derives parser-normalized expressions for the canonical payload, valid-time, and system-time CHECKs from a session-local temporary probe table on the same PostgreSQL runtime.

The final row-admission gate admits a CHECK only when all of the following are true:

- it has the exact package-owned canonical name;
- it is a validated inheritable CHECK; and
- `pg_get_expr(conbin, conrelid, false)` exactly equals the corresponding same-runtime canonical probe expression.

The probe table is dropped before production admission continues. The final gate does not repair a mismatched CHECK. Migration 0008 owns convergence; migration 0009 owns fail-closed final verification. This preserves a single repair authority while ensuring restore/operator drift cannot turn a canonical name into semantic authority.

Unknown or drifted constraints are not auto-dropped by migration 0009. Their ownership and data-validity consequences require explicit operator reconciliation or reapplication of the package-owned convergence migration.

Package migration 0009 and its Docker initializer must remain byte-identical.

## Alternatives rejected

Trusting canonical constraint names was rejected because names identify catalog objects, not their Boolean semantics.

Trusting only `convalidated` was rejected because validation says PostgreSQL has checked a particular stored expression; it does not prove that expression is the package-owned lifecycle grammar.

Copying a hard-coded deparser string into migration 0009 was rejected because PostgreSQL decompiled expression text can be version-sensitive. A same-runtime temporary probe follows the existing migration-0008 strategy and binds comparison to the parser/catalog representation actually in use.

Automatically repairing or dropping a mismatched CHECK in migration 0009 was rejected because 0008 already owns convergence. Duplicating repair authority would create two mutable convergence implementations and make migration-order evidence harder to reason about.

## Verification

Test-first commit `d0f52e780d298c92ced71adae8523ae8d48e19ad` adds a real PostgreSQL specimen and wires it into the container CI lane. The specimen replaces `ck_llm_context_lifecycle_outbox_payload_canonical_v1` with the same name but a stricter predicate, proves that the replacement rejects an otherwise canonical lifecycle event, then requires migration 0009 itself to fail with the fixed content-free row-admission authority error.

Causal fix `47ccd293d54fd28e51090aca39af285346673f0a` adds same-runtime payload/valid-time/system-time probe expressions to both byte-identical migration-0009 copies and requires exact expression equality at final admission.

Hosted exact-head PostgreSQL execution is required before this ADR may move to Accepted.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: 5.5. Constraints*. https://www.postgresql.org/docs/18/ddl-constraints.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: 9.27. System information functions and operators*. https://www.postgresql.org/docs/18/functions-info.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: 52.13. pg_constraint*. https://www.postgresql.org/docs/18/catalog-pg-constraint.html
