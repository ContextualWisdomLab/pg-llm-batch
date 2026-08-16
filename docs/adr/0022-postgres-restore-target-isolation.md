# ADR 0022: Isolate restore-target libpq service names

- **Status:** Accepted for the bounded restore-target identity seam
- **Date:** 2026-08-16

## Context

Protected main can inspect packaged schema bytes and a caller-owned backup
artifact. Active writers own `pg_dump` (#208), custom-format `pg_restore`
(#212), receipt binding (#215), catalog acceptance (#223), receipt
re-inspection (#221), and the physical/PITR profile (#219).

#212 accepts one `service_name` and does not compare it to the live
service. An operator can therefore point `pg_restore` at the production
`pg_service.conf` entry and still satisfy the restore executor. NIST SP
800-34 treats an alternate processing site as a distinct recovery
identity, not a reuse of the live system (Swanson et al., 2010).

## Decision

`verify_postgres_restore_target_isolation()` accepts only:

- `live_service_name`; and
- `restore_service_name`.

Both must be exact built-in strings matching the same libpq service-name
grammar used by the logical dump and restore executors. The names must
differ. DSNs, passwords, hosts, ports, `tenant_scope`, and backup-byte
arguments are not accepted. This record is ADR 0022 so it does not collide
with #212 ADR 0016, #215 ADR 0017, #223 ADR 0018, #219 ADR 0019, #221
ADR 0020, or #222 ADR 0021.

```mermaid
flowchart TD
    A[Name live pg_service] --> C{exact distinct names}
    B[Name isolated restore pg_service] --> C
    C -->|no| D[Stop before pg_restore]
    C -->|yes| E[Operator continues isolated restore outside this seam]
```

## Consequences

Hosts can prove the restore-drill service is not the live service before
they invoke `pg_restore`. The seam does not execute dump or restore, open
a connection, or claim RPO/RTO, CSAP, or SOC 2 readiness. Logical restore
remains #208/#212. Catalog acceptance remains #223.

## Rollback

Delete the isolation module, tests, doctoring, and this decision record.
No schema migration is required.

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
