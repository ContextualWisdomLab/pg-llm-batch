# Doctoring: legacy PostgreSQL extension retirement

## Evidence-based decision

PostgreSQL extension membership and dependency handling remain database-owned. PostgreSQL 18 documents that `DROP EXTENSION` removes an extension's member objects. `RESTRICT` blocks ordinary dependent objects, while `CASCADE` can recursively remove additional dependents. PostgreSQL's dependency catalog also distinguishes extension membership (`pg_depend.deptype = 'e'`) from auto-extension dependencies (`deptype = 'x'`), the latter created by `DEPENDS ON EXTENSION`. Both classes are tied to extension removal closely enough that `RESTRICT` alone is not a preservation guarantee for operator or application objects in those classes.

The product therefore combines two boundaries instead of treating `RESTRICT` as sufficient by itself. A product-specific `pg_depend` preflight first fails closed on every explicit auto-extension dependency and on unexpected table-like extension members outside the expected `pg_cron` relations in the `cron` schema. Only after those auto-drop cases have been dispositioned does PostgreSQL `DROP EXTENSION ... RESTRICT` provide the final database-owned guard for ordinary external dependencies.

PostgreSQL 18 also defines `lock_timeout` as a per-lock-acquisition bound and advises against setting it globally. The migration uses `SET LOCAL lock_timeout = '5s'` inside its own transaction so the bound applies only to this operator action.

The remaining product-specific preflight is stricter than PostgreSQL requires: no cron job may remain and no function with a retired package signature may remain. These checks prevent extension retirement from overriding independent operator scheduling authority or misclassifying a modified helper as disposable package state.

## Safety claims and limits

Supported claims:

- failure before `COMMIT` leaves no partial extension retirement;
- the `pg_depend` preflight preserves the reviewed application/operator classes that `RESTRICT` would otherwise remove with an extension: explicit `DEPENDS ON EXTENSION` objects and unexpected table-like extension members;
- `RESTRICT` remains the final fail-closed boundary for ordinary external dependencies after those auto-drop classes have been screened;
- `gateway_retrieval_logs` is not a migration target and is asserted present by the live smoke when it existed beforehand;
- successful replay is idempotent; and
- package and host configuration removal is deliberately outside this database migration.

Unsupported claims:

- automatic rollback recreates extensions or schedules;
- every extension dependency can be classified without operator review;
- every normal extension member is application-owned merely because it has `deptype = 'e'`;
- removing an extension-membership or `DEPENDS ON EXTENSION` edge is safe without a reviewed ownership decision;
- a same-signature function is necessarily package-owned;
- retirement proves distributed exactly-once provider processing; or
- migration success alone authorizes removal of operating-system packages from every environment.

## Verification mapping

| Risk | Evidence |
| --- | --- |
| Package schedule still active | exact job name and command preflight plus live smoke |
| Independent cron authority | all remaining `cron.job` rows block retirement |
| Modified helper deletion | any remaining retired signature blocks retirement |
| Application table enrolled as extension member | `pg_depend` `e` guard plus live `ALTER EXTENSION http ADD TABLE gateway_retrieval_logs` refusal fixture |
| Explicit `DEPENDS ON EXTENSION` object | `pg_depend` `x` guard plus live operator-routine refusal fixture |
| Ordinary external dependency removal | `RESTRICT` required after the auto-drop preflight; `CASCADE` statically forbidden |
| Partial two-extension change | one transaction and bounded local lock wait |
| Evidence loss | no table/schema drops; live `gateway_retrieval_logs` assertion before and after retirement |
| Unsafe retry | failed transaction rollback and successful double execution |

## References

PostgreSQL Global Development Group. (2026). *DROP EXTENSION*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-dropextension.html

PostgreSQL Global Development Group. (2026). *The pg_depend catalog*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/catalog-pg-depend.html

PostgreSQL Global Development Group. (2026). *Client connection defaults*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/runtime-config-client.html

PostgreSQL Global Development Group. (2026). *Packaging related objects into an extension*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/extend-extensions.html
