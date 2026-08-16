# PostgreSQL restore-target isolation

This record is the operator contract for
`verify_postgres_restore_target_isolation()` and ADR 0021. Use it after you
have a stored recovery receipt and before you run `pg_restore`. The function
proves that the restore-drill libpq service name is distinct from the live
service. It does not accept a DSN, and it does not run `pg_dump` or
`pg_restore`.

## What to do next

1. Choose the live `pg_service.conf` name that currently serves production
   batch traffic. Do not copy a DSN, password, or `tenant_scope` into this
   seam.
2. Provision a separate restore-drill service name that points at an empty
   isolated cluster. Keep that name out of the live service file entry.
3. Call `verify_postgres_restore_target_isolation(live_service_name=...,
   restore_service_name=...)`. Both values must be exact built-in strings
   that match the reviewed libpq service-name grammar.
4. Continue to a reviewed isolated restore only when verification returns.
   Distinct names are not proof that restore, RLS, PITR, or a live cluster
   succeeded, and they are not a package capability claim.
5. If verification raises `PostgresRestoreTargetError`, stop. Do not reuse
   the live service name. Do not edit names by hand to force a match. Create
   or select a different restore-drill service, then retry.

## Evidence boundary

The verifier compares only:

- `live_service_name`; and
- `restore_service_name`.

It rejects subclasses, bytes, namespace substitutes, DSNs, paths, blank
names, and names outside the libpq service-name grammar before comparing
identity. It does not accept a parallel DSN, password, host, port,
`tenant_scope`, or backup-byte argument. Exception text stays content-free.

This slice does not execute `pg_dump` or `pg_restore`, does not prove a
backup is restorable, and does not establish RPO/RTO, CSAP, or SOC 2
readiness. It never emits a package capability claim.

## Failure handling

Invalid name types or grammar raise a fixed inputs error. An exact name
match raises a fixed isolation error. Lower-layer values never enter the
exception text.

## References

Swanson, M., Bowen, P., Phillips, A., Gallup, D., & Lynes, D. (2010).
*Contingency planning guide for federal information systems* (NIST
Special Publication 800-34 Rev. 1). National Institute of Standards and
Technology. https://doi.org/10.6028/NIST.SP.800-34r1

Joint Task Force. (2020). *Security and privacy controls for information
systems and organizations* (NIST Special Publication 800-53 Rev. 5).
National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-53r5

MITRE. (2026). *CWE-669: Incorrect resource transfer between spheres*.
https://cwe.mitre.org/data/definitions/669.html

The PostgreSQL Global Development Group. (2026). *Backup and restore*.
PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/backup.html

The PostgreSQL Global Development Group. (2026). *The connection service
file*. PostgreSQL 18 documentation.
https://www.postgresql.org/docs/18/libpq-pgservice.html
