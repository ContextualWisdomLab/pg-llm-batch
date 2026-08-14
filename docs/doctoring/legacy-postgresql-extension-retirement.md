# Doctoring: legacy PostgreSQL extension retirement

## Evidence-based decision

PostgreSQL extension membership and dependency handling remain database-owned. PostgreSQL 18 documents that `DROP EXTENSION` removes extension members and that `RESTRICT` prevents the drop when other objects depend on the extension; `CASCADE` would recursively remove dependent objects. The product therefore uses `RESTRICT` as a destructive-change safety boundary rather than trying to predict every dependency in application code.

PostgreSQL 18 also defines `lock_timeout` as a per-lock-acquisition bound and advises against setting it globally. The migration uses `SET LOCAL lock_timeout = '5s'` inside its own transaction so the bound applies only to this operator action.

The product-specific preflight adds stricter rules than PostgreSQL requires: no cron job may remain, and no function with a retired package signature may remain. These checks prevent extension retirement from overriding independent operator scheduling authority or misclassifying a modified helper as disposable package state.

## Safety claims and limits

Supported claims:

- failure before `COMMIT` leaves no partial extension retirement;
- `RESTRICT` prevents unreviewed dependent-object deletion;
- `gateway_retrieval_logs` is not a migration target and is asserted present by the live smoke when it existed beforehand;
- successful replay is idempotent; and
- package and host configuration removal is deliberately outside this database migration.

Unsupported claims:

- automatic rollback recreates extensions or schedules;
- every extension dependency can be classified without operator review;
- a same-signature function is necessarily package-owned;
- retirement proves distributed exactly-once provider processing; or
- migration success alone authorizes removal of operating-system packages from every environment.

## Verification mapping

| Risk | Evidence |
| --- | --- |
| Package schedule still active | exact job name and command preflight plus live smoke |
| Independent cron authority | all remaining `cron.job` rows block retirement |
| Modified helper deletion | any remaining retired signature blocks retirement |
| Destructive dependency removal | `RESTRICT` required; `CASCADE` statically forbidden |
| Partial two-extension change | one transaction and bounded local lock wait |
| Evidence loss | no table/schema drops; live `gateway_retrieval_logs` assertion |
| Unsafe retry | failed transaction rollback and successful double execution |

## References

PostgreSQL Global Development Group. (2026). *DROP EXTENSION*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-dropextension.html

PostgreSQL Global Development Group. (2026). *Client connection defaults*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/runtime-config-client.html

PostgreSQL Global Development Group. (2026). *Packaging related objects into an extension*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/extend-extensions.html
