# Lifecycle outbox nested `SECURITY DEFINER` authority

## Finding

The lifecycle-outbox runtime guard previously inspected user-schema `SECURITY DEFINER` routines only when a runtime-selectable role itself had schema `USAGE` and routine `EXECUTE`. That direct-edge model is incomplete. A runtime caller can execute an outer `SECURITY DEFINER` owned by an otherwise ordinary role; while the outer routine is running, PostgreSQL evaluates its work with that owner principal. If the outer owner can execute a second `SECURITY DEFINER`, the second routine runs with its own owner principal. The runtime caller therefore does not need direct `EXECUTE` on the privileged inner routine.

The concrete acceptance specimen separates the principals deliberately. The runtime caller has only outbox `SELECT, INSERT`. The outer owner has no forbidden outbox or cluster authority and alone receives `EXECUTE` on the inner routine. The inner owner alone has outbox `TRUNCATE`. The inner routine is revoked from `PUBLIC`; the caller can execute only the outer routine. Calling the outer routine still empties the outbox, proving a real two-hop executable-principal path rather than a source-text or hypothetical dependency.

## Authority model

Runtime admission now computes a cycle-safe recursive closure of user-schema `SECURITY DEFINER` owners. The seed consists of definers executable by each runtime-selectable/administerable role through both schema `USAGE` and routine `EXECUTE`. For every discovered owner, the recursive step follows any further non-system-schema `SECURITY DEFINER` that owner can execute through the same privilege pair. `UNION` de-duplicates owner OIDs so cycles terminate.

Every owner in that executable closure is checked against the existing forbidden envelope: `SUPERUSER`, `CREATEROLE`, `REPLICATION`, `BYPASSRLS`, outbox ownership/exercisable owner authority, delegable outbox `SELECT`/`INSERT`, `TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, `TRIGGER`, and the existing membership-administration graph that can redistribute forbidden authority. Direct callable-definer `CREATEDB` retains ADR 0032's narrower treatment because PostgreSQL prohibits `CREATE DATABASE` inside a transaction block; `CREATEDB` remains forbidden when it can be granted onward for later invoker-context use.

This guard is intentionally authority-based, not function-body-based. Parsing a routine body would not provide stable authority across PL/pgSQL, SQL-language routines, dynamic SQL, extension languages, replaced routines, or indirect calls. The package instead refuses to enter a definer principal whose live executable authority graph reaches another privileged definer principal. This can reject a routine that never happens to call one of the privileged routines its owner may execute; that conservatism is deliberate at the tenant/application isolation boundary.

PostgreSQL documents `SECURITY DEFINER` functions as executing with the privileges of the function owner, and documents `EXECUTE` as the privilege permitting a function or procedure call. PostgreSQL's information functions expose `has_function_privilege` and `has_schema_privilege` for these live authorization checks. Those primary semantics are the basis for following executable owner principals rather than only the original runtime caller.

## TDD and executable traceability

- Static RED `154d2a60324791cead1e41266e54696ba8d51650` requires recursive executable-owner authority in the admission SQL.
- Causal production repair `a4a4e11381e6bcd6700ddf7ab2fbe945536b81a1` replaces direct-only definer-owner inspection with the recursive closure while retaining one fail-closed catalog admission round trip.
- PostgreSQL specimen `6c7a4e32e6ccfbb751732af7d3a40e299fb1d8d7` proves the ordinary caller can reach an inner definer owner's RLS-exempt `TRUNCATE`, then requires package admission to reject the latent path. Revoking only the outer owner's inner-routine `EXECUTE` is the positive control and must restore package access.
- CI wiring `2f8a2fc0f80c83fa2219980ea522f5077380085f` adds the specimen to the PostgreSQL/container lane.
- ADR 0032 update `544211a048eb87595fd117d6cf223d789fa92065` keeps the decision Proposed until an unchanged exact repaired head executes all required tests and PostgreSQL smokes successfully.

No migration, ACL, role membership, routine ownership, or routine body is silently rewritten by runtime admission. A deployment that exposes this path must remove the executable edge or separate the principal/connection through operator-owned authorization changes.

## References

PostgreSQL Global Development Group. (2026a). *CREATE FUNCTION*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-createfunction.html

PostgreSQL Global Development Group. (2026b). *Privileges*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/ddl-priv.html

PostgreSQL Global Development Group. (2026c). *System information functions and operators*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/functions-info.html
