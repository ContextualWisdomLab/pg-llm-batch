# Architecture

## Deployment boundary

`pg-llm-batch` remains independently deployable and embeddable. PostgreSQL owns
configuration, encrypted secrets, token counting, JSONL payloads, and durable
provider lifecycle state. Provider HTTP behavior remains behind
`BatchAPIClient`, while host services may inject credential, observation-order,
and lifecycle-persistence seams without changing provider semantics.

## Durable lifecycle tenancy

`DurableBatchAPIClient` is the backward-compatible standalone facade.
`TenantDurableBatchAPIClient` requires a tenant scope selected by a trusted host
after authentication and authorization. The durable business identity is:

```text
(tenant_scope, endpoint_alias, remote_batch_id)
```

Package reads and writes bind the validated scope with parameterized,
transaction-local `set_config('pg_llm_batch.tenant_scope', ..., true)`.
PostgreSQL row-level security is enabled and forced, so missing context is
default-deny for ordinary application roles. PostgreSQL superusers and roles
with `BYPASSRLS` remain administrative escape hatches and must not be used as
application identities. Lifecycle-outbox runtime data access enforces that
boundary at each caller-owned transaction seam by reading the effective
`CURRENT_USER` from `pg_catalog.pg_roles`, joining the live canonical relation,
and requiring `NOSUPERUSER NOBYPASSRLS`, enabled and forced RLS, and separation
from exercisable table-owner authority before tenant state is bound or durable
rows are touched. Exact owner identity is rejected. PostgreSQL 16+ role semantics
are followed rather than treating membership alone as authority: inherited
`USAGE`, `SET ROLE`, or membership administration over the owner role is rejected,
while inert membership with none of those privilege paths is not. The check
follows effective role, not DSN text or session identity, and stays within the
existing single catalog round trip. Installation and migration remain separate
operator-authority paths. ADR 0031 records this runtime owner-separation boundary.

Runtime relation privileges are part of the same application-authority boundary.
The application identity is rejected when it holds outbox `TRUNCATE`, `DELETE`,
any table-level or column-level `REFERENCES`, or `TRIGGER` authority. `TRUNCATE`
is whole-table authority outside row-security filtering. `DELETE` remains
RLS-filtered, but the outbox is append-only durable publication intent: a tenant
runtime role that can delete its own committed row can erase replay/conflict
evidence and make a later event appear to be a first write. `REFERENCES` and
`TRIGGER` can establish relation behavior outside the package's tenant-qualified
DML contract. Admission uses schema-qualified
`pg_catalog.has_table_privilege` for `TRUNCATE`/`DELETE`/`TRIGGER` and
`pg_catalog.has_any_column_privilege` for `REFERENCES`, so column-specific grants
fail closed too. This does not ban ordinary supported RLS-subject DML: the
compare-and-swap path deliberately retains the minimum `UPDATE` authority
PostgreSQL requires for `SELECT ... FOR UPDATE`. ADR 0031 and
`docs/doctoring/lifecycle-outbox-runtime-role-authority.md` record the operator /
runtime separation and audit surface.

Lifecycle-outbox RLS policy authority is catalog-verified, not name-inferred.
Canonical v2 uses `OPERATOR(pg_catalog.=)` and `pg_catalog.current_setting` for
both `USING` and `WITH CHECK`. Migration 0008 accepts an existing v2 without DDL
only when `pg_policy` proves all-command permissive `PUBLIC` scope and both
stored expression trees decompile to the canonical tenant predicate. A
same-name drifted v2 is replaced, an unknown policy name fails the migration
instead of being silently retained or deleted, and the canonical catalog state
is verified again before v1/legacy policies are retired. Policy names remain
version markers rather than security evidence.

Final row-admission independently verifies that RLS authority still exists after
convergence. Migration 0009 requires both `pg_class.relrowsecurity` and
`relforcerowsecurity`, exactly one outbox policy, and the exact canonical-v2
command/mode/`PUBLIC` role plus `USING`/`WITH CHECK` expression identity and
reviewed function/operator dependency boundary. This catches restore/operator
drift that disables RLS while retaining policy rows or recreates the canonical
policy name with widened predicates after migration 0008 was previously
recorded as applied. Migration 0009 does not repair RLS drift; migration 0008
remains the sole convergence owner. ADR 0027 records the final-verifier boundary.

Lifecycle-outbox payload and timestamp CHECK authority is executable catalog
identity, not a constraint name or comment alone. Migration 0008 requires each
canonical CHECK to be validated and inheritable, to carry the expected review
stamp, and to have a `pg_get_expr` result equal to the reviewed definition as
parsed by the same running PostgreSQL server. The migration derives that
comparison value from session-local temporary probe CHECKs, drops the probe,
repairs a drifted package-owned canonical constraint once, and verifies the
stored predicate again. Already-current durable constraints avoid replacement
DDL. The comment remains traceability evidence but cannot by itself make a
same-name different predicate canonical.

Final row-admission independently repeats that semantic proof. Migration 0009
constructs its own same-runtime payload, valid-time, and system-time CHECK probe,
then admits each package-owned CHECK only when its exact canonical name,
validation/inheritance state, and `pg_get_expr` output match the corresponding
probe expression. This catches restore or operator drift that occurs after
migration 0008 was previously recorded as applied. Migration 0009 does not
repair a mismatched CHECK; migration 0008 remains the sole convergence owner and
the final gate fails closed for explicit operator reconciliation. ADR 0026
records this separation of convergence and final semantic admission authority.

Lifecycle-outbox replay idempotency has a separate catalog invariant. Runtime
uses `ON CONFLICT (tenant_scope, evidence_id) DO NOTHING`; migration 0008
therefore converges `uq_llm_context_lifecycle_outbox_tenant_evidence` after
`CREATE TABLE IF NOT EXISTS` and accepts it only as a validated, nondeferrable
UNIQUE constraint over exactly those two columns. A pre-existing table with a
missing, deferrable, wrong-kind, or wrong-column same-name constraint is repaired
once. Existing duplicate durable identities fail migration rather than being
silently merged or discarded. A current canonical replay arbiter is left
untouched on reapplication.

Lifecycle-outbox runtime relation authority is explicit without rewriting
caller transaction state. Tenant binding calls `pg_catalog.set_config` directly,
and runtime reads/writes address
`public.llm_context_lifecycle_outbox`. The earlier candidate that used
`SET LOCAL search_path` in this caller-owned seam was superseded because its
name-resolution change would persist for unrelated domain SQL until transaction
end.

The durable outbox relation itself is also part of the admitted persistence
contract. Migration 0008 accepts only an ordinary (`pg_class.relkind = 'r'`),
logged (`relpersistence = 'p'`) table in `public`. A structurally identical
`UNLOGGED` replacement fails closed before constraint, RLS, or index convergence;
PostgreSQL does not WAL-log unlogged-table data, truncates it after a crash or
unclean shutdown, and does not replicate its contents to standbys. The migration
does not silently issue `SET LOGGED`, because that rewrite and its operational
impact require an operator-controlled reconciliation window.

Final row-admission independently re-proves relation durability, topology, and
storage-method authority after convergence. Migration 0009 requires the
canonical object to remain one ordinary logged table in `public`, rejects any
`pg_inherits` edge where the outbox is a parent or child, and resolves
`pg_class.relam` through `pg_am` to the reviewed built-in `heap` TABLE access
method. This catches post-0008 `SET UNLOGGED`, inheritance drift, and
`ALTER TABLE ... SET ACCESS METHOD` changes even when columns, RLS, CHECKs,
replay constraints, defaults, trigger/rule catalogs, and indexes are otherwise
unchanged. The final verifier performs no storage rewrite or hierarchy repair;
operators must reconcile possible unlogged-interval loss, child/parent data, and
any interval governed by an unreviewed table access method before re-admission.
ADR 0030 records this final relation-authority boundary.

Exact durable row-shape admission is physical/catalog-aware rather than limited
to SQL-visible columns. Migration 0008 requires exactly the 14 package-owned live
positive-numbered user attributes and also rejects any positive-numbered
`pg_attribute.attisdropped` entry. PostgreSQL retains a dropped column physically
while hiding it from SQL parsing, so `DROP COLUMN` is not treated as proof that a
previously undeclared persistence surface never existed. The migration does not
auto-rewrite the table or reclaim that state; retention, legal-disposal, WAL,
locking, and availability consequences require operator-controlled
reconciliation or rebuild.

Final row-admission re-proves that complete column catalog rather than trusting
migration 0008 history. Migration 0009 requires the same exact 14 live column
names, PostgreSQL types and type-default collations, reviewed `NOT NULL` and
default-presence state, no generated/identity authority, and no positive-numbered
dropped-column tombstones. This is necessary because PostgreSQL CHECK predicates
accept `UNKNOWN` and ordinary UNIQUE constraints treat nulls as distinct: a
post-convergence `DROP NOT NULL` on `evidence_id` can otherwise admit multiple
NULL replay identities without changing the canonical CHECK or UNIQUE objects.
Migration 0009 never repairs this state; invalid rows and the catalog change
require explicit operator reconciliation before `NOT NULL` can be restored. ADR
0029 records the final-column authority decision.

Executable table programs are part of the same authority at both convergence and
final admission. Migration 0008 rejects any non-internal `pg_trigger` attached
to the lifecycle outbox and any `pg_rewrite` rule whose event relation is the
outbox before later CHECK, RLS, UNIQUE, or index convergence. Migration 0009
independently repeats those catalog checks so a restore or manual DDL operation
cannot attach a user trigger or rewrite rule after 0008 was previously recorded
as applied and still pass the final row-admission gate. PostgreSQL-internal
constraint triggers remain admissible; unknown user triggers and rules are not
silently deleted because the package cannot prove their ownership, external
dependencies, or side effects. Migration 0008 remains the convergence owner and
0009 remains fail-closed verification. ADR 0024 records this boundary and the
PostgreSQL catalog evidence behind it.

Declared defaults are executable row-admission authority whenever a caller omits
a column or explicitly requests `DEFAULT`. The package runtime deliberately
omits `context_outbox_uuid` and `created_at`, while the reviewed schema retains
`tenant_scope DEFAULT 'standalone'` for direct/operator SQL compatibility even
though package writes validate and supply tenant scope explicitly. Migration
0008 converges all three default contracts, but a restore or later operator DDL
can replace one after 0008 was recorded as applied without changing CHECK, RLS,
trigger/rule, replay, or index state. Migration 0009 therefore re-reads
`pg_attribute` and `pg_attrdef` and admits only `tenant_scope` as live NOT NULL
`text` with exact `'standalone'::text`, `context_outbox_uuid` as live NOT NULL
`uuid` with exact `gen_random_uuid()`, and `created_at` as live NOT NULL
`timestamptz` with exact `now()`; generated/identity substitutes are rejected.
The final gate never rewrites a drifted default, leaving migration 0008 as the
single convergence authority. The standalone default is compatibility schema,
not tenant-authentication authority; arbitrary direct SQL remains outside the
package RLS guarantee. ADR 0028 records this boundary.

Index-program authority extends beyond explicit expressions and predicates.
Migration 0009 rejects expression and partial indexes and requires every direct
index key to use the default `pg_catalog` operator class for the exact indexed
column type and the index relation's access method. This permits ordinary
PostgreSQL-core simple-column indexes, including a nonunique hash index, while
rejecting a custom operator class whose support functions would execute during
index maintenance. Unknown index programs are not auto-dropped because their
function dependencies, performance role, and ownership require operator
reconciliation. ADR 0025 records this boundary.

Migration 0008 and its destructive rollback are installer-owned atomic
statements and bind `pg_catalog, public, pg_temp` with fully qualified
`pg_catalog.set_config` inside their `DO` blocks before object lookup or DDL.
Explicit `pg_temp` placement prevents the temporary schema from receiving
implicit relation precedence over the reviewed `public` application schema in
those statements. This does not make `public` safe if operators grant untrusted
principals `CREATE` there; schema ACLs remain part of the deployment trust
boundary.

The custom setting is part of a **trusted application boundary**. It is not a
credential and is not a substitute for authentication, authorization,
SQL-injection prevention, or restricted direct database access. A role capable
of arbitrary SQL can call `set_config` with an arbitrary tenant scope. CWL hosts
must therefore expose tenant lifecycle operations through parameterized package
APIs or a separately reviewed identity-to-role interface, not a generic SQL
surface.

Provider metadata, endpoint aliases, provider resource identifiers, payloads,
model output, and transport headers never select tenant authorization context.

## Migration and rollback

Legacy lifecycle rows are backfilled to `standalone` without deletion or
identity merging. The prior endpoint/provider unique key is replaced by a
tenant-qualified key. The owner-enforcement transition, backfill, constraint
migration, and forced-RLS restoration execute in one PostgreSQL anonymous block
so psql autocommit cannot commit an intermediate owner-bypass state.

The Context Fabric lifecycle outbox separately converges its runtime replay key
on every migration application. A fresh table receives the canonical UNIQUE
constraint during creation and then satisfies the catalog guard without further
DDL. A pre-existing table must acquire the same validated NOT DEFERRABLE
`(tenant_scope, evidence_id)` constraint before migration succeeds; duplicates
are an explicit operator-reconciliation failure.

Enabling RLS changes the behavior of direct SQL integrations: an ordinary role
that does not bind an authorized transaction-local scope sees no lifecycle
rows. Those integrations must move to `get_remote_batch_state`,
`get_tenant_remote_batch_state`, or a reviewed tenant-binding database interface
before deployment. Caller-owned outbox methods require a real transaction for
the transaction-local tenant setting, but preserve the caller's existing
`search_path`.

Rollback to the former two-column key is unsafe until an operator proves that no
`(endpoint_alias, remote_batch_id)` pair exists in more than one tenant scope.
The rollback binds reviewed name resolution before `to_regclass`, emptiness
inspection, and `DROP TABLE`. The packaged schema and Docker initialization
schema are maintained as exact mirrors and must be reapplied successfully more
than once.

## Logical restore execution

`restore_postgres_logical_backup()` is a bounded direct-SQL restore seam. The
caller must pass exact-boolean `source_superusers_trusted=True` and select an
isolated libpq service; the service name is not an authorization or
proof-of-isolation boundary. Only `PGPASSWORD`, `PGPASSFILE`, and
`PGSERVICEFILE` may be inherited. The child runs
`pg_restore --single-transaction --exit-on-error --dbname=service=...`.

Custom-format `pg_restore` seeks to the table of contents and data blocks, so a
successful restore is not required to leave the descriptor at end-of-file.
Post-restore metadata mismatch is fail-closed and must be treated as unsafe
because the SQL transaction may already have committed. This seam does not
complete isolated schema/RLS/PITR acceptance.

## Modular interoperability

CWL hosts such as `contextual-orchestrator` and `naruon` supply tenant context
only after their own authentication and authorization boundary. The package
does not require either host and retains standalone operation. When embedded,
tenant scope is a local control-plane identity and not model- or
provider-returned data.

## Verification boundary

Deterministic gates cover strict tenant validation, standalone compatibility,
tenant-qualified SQL parameters, current-state reconciliation, migration
idempotency, malformed database rows, default-deny policy text, explicit
`pg_catalog` policy predicate authority, `pg_policy` command/role/expression
identity, unknown-policy fail-closed behavior, post-repair canonical policy
verification, final relation-level RLS enable/force and policy-semantic
reverification, effective-`CURRENT_USER` runtime admission requiring exact
`NOSUPERUSER NOBYPASSRLS`, live enabled/forced RLS, exact owner inequality,
absence of exercisable owner-role `USAGE`, `SET`, or membership-admin authority,
and absence of outbox `TRUNCATE`, `DELETE`, table/column `REFERENCES`, or
`TRIGGER` authority before tenant state or outbox-row access, canonical
payload/timestamp CHECK type/validation/inheritance, same-runtime
parsed-expression identity in both convergence and final row-admission,
review-stamp traceability, post-repair CHECK verification, canonical replay
UNIQUE kind/validation/deferrability/column identity, ordinary logged-public
relation identity at convergence and final admission, exact live-column
cardinality, dropped-column tombstone rejection, complete final `pg_attribute`
type/collation/nullability/default-presence/generated/identity/cardinality
re-verification, no outbox inheritance edge at convergence or final admission,
built-in `heap` TABLE access-method identity at final admission, non-internal
trigger and rewrite-rule rejection at both convergence and final admission,
exact retained `tenant_scope` standalone plus omitted-column UUID/created-at
default authority at final admission, expression/partial/custom-operator-class
index-program rejection, default-core simple-index admission, runtime schema
qualification without caller `search_path` mutation, installer/rollback
search-path authority, schema mirroring, operator documentation, and 100%
production statement and branch coverage. Live PostgreSQL isolation tests use a
`NOSUPERUSER NOBYPASSRLS` role and prove that identical provider identifiers in
different tenants remain independently addressable and mutually invisible when
access occurs through the trusted package boundary. Exact-head runtime evidence
must additionally prove that a `BYPASSRLS` role can bypass the policy at
PostgreSQL level but is rejected by the package before tenant binding/data SQL,
that superuser effective authority is rejected, that a normal table owner can
remove `FORCE ROW LEVEL SECURITY` and thereby expose both tenant rows but is
itself rejected by the package, that a normal non-owner `TRUNCATE` role can
remove all tenant rows despite forced RLS, that a normal tenant `DELETE` role can
erase its own committed durable intent while the other tenant remains hidden,
that column-level `REFERENCES` can create a dependency on the canonical replay
key, that `TRIGGER` can attach executable relation behavior, and that production
admission rejects each of those authorities before tenant/data SQL. `SET ROLE`
must change admission according to effective `CURRENT_USER` rather than DSN
text. The same evidence must exercise a non-default caller `search_path`, verify
the canonical outbox relation is still selected, verify the caller path is
unchanged afterward, and execute migration 0008/0009 against stale replay-key,
spoofed canonical-CHECK, final-gate same-name CHECK-expression drift,
disabled-RLS and same-name widened-policy drift, UNLOGGED-relation at convergence
and after convergence, undeclared-live-column, dropped-column-tombstone,
post-convergence column-nullability drift, inheritance-edge at convergence and
after convergence, post-convergence non-`heap` table-access-method drift,
convergence-time and post-convergence user-trigger/rewrite-rule, omitted-column
default-program including retained `tenant_scope` compatibility-default drift,
executable-index, and custom-operator-class variants so PostgreSQL evaluates
canonical RLS policy, CHECK-predicate, UPSERT-arbiter, relation/column catalog,
declared-default, executable-table/index-program, storage-method, and
durability/schema conditions. These tests do not claim isolation after arbitrary
SQL or untrusted schema-creation authority is granted.
