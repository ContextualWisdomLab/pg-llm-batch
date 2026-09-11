# Threat model

## Authority

This model describes protected-main `pg-llm-batch` assets, trust boundaries, attacker capabilities, mitigations, and residual risk. It is evidence readiness for SOC 2 / CSAP preparation, not certification, penetration-test evidence, or production authorization.

The methodology follows data-centric threat modeling and NIST risk assessment: identify data, systems, threat sources, preconditions, controls, and residual risk. Controls are aligned to NIST SP 800-53 Revision 5.

## What operators must do

1. Select `tenant_scope` only behind an authenticated and authorized host boundary.
2. Do not grant arbitrary SQL, `SUPERUSER`, or `BYPASSRLS` to ordinary application roles.
3. Preserve authorized business payloads unless an explicit host policy transforms them with provenance and acceptance tests.
4. Treat recovery receipt/hash evidence as identity/integrity metadata, not restorability.
5. Treat Fernet as optional protected-main behavior. Compatibility mode can persist `is_encrypted = FALSE`; production encryption policy, migration, rotation/recovery, and external key custody remain separate responsibilities.
6. Before logical restore, obtain live and restore `system_identifier` values from caller-opened connections and use the protected restore-target verifier. Do not treat that comparison as authentication of the connections or as post-restore application readiness.
7. Use the explicit `standalone` scope for a single-tenant operator; do not reinterpret it as anonymous public tenancy.

## Assets

| Asset | Location | Buyer relevance |
| --- | --- | --- |
| Authorized prompts, JSONL, provider results | package payload/request tables and provider files | Business meaning; silent transformation invalidates accounting/replay. |
| Durable lifecycle identity | `llm_remote_batch_jobs`, keyed by `(tenant_scope, endpoint_alias, remote_batch_id)` | Cross-tenant lifecycle isolation. |
| Result checkpoints | `llm_result_stream_checkpoints`, keyed by tenant + consumer + provider identity | Resumable prefix evidence; not whole-stream authenticity. |
| Standalone config/secrets | `com_config`, `com_secrets` | Optional Fernet plus explicit base64 compatibility mode. |
| Provider credentials | host credential provider or standalone store | Never tenant-selected authority or telemetry content. |
| Recovery evidence | receipts/hashes/schema evidence | Content-free identity/integrity, not restore success. |
| Restore target identity | exact libpq service names + caller-owned PostgreSQL `system_identifier` values | Detects same-name and same-cluster aliasing before a host proceeds. |

## Trust boundaries

```text
[Caller / operator]
        | authentication + authorization + connection provenance (host-owned)
        v
[Host control plane] -- chooses tenant, credentials, DSN/service, recovery target
        | package Python API / CLI
        v
[pg-llm-batch] -- validates and bounds inputs/effects
        | parameterized SQL / bounded subprocess seams
        v
[PostgreSQL] -- forced tenant RLS + caller-opened recovery connections
        |
        +--> [Provider Batch API] untrusted external data
        +--> [Caller-owned backup/WAL/key infrastructure]
```

`tenant_scope` is routing context written through parameterized transaction-local `set_config`; it is not a credential. A role with arbitrary SQL can choose a custom-setting value. RLS therefore augments, rather than replaces, host authentication/authorization and SQL-injection prevention.

The restore-target verifier has a similarly bounded trust model. `postgres_restore_target.py` does not open either database connection. The caller supplies service names and `PostgresRestoreTargetIdentity(system_identifier=...)` values collected from already-opened connections. Distinct exact names and identifiers reject obvious same-cluster aliases, but the package does not authenticate the collector, the connection setup, or the mapping from a service name to the supplied identifier.

## Threat sources and controls

| Threat source | Needed precondition | Protected-main mitigation | Residual risk |
| --- | --- | --- | --- |
| Confused-deputy tenant selection | Host accepts provider/model/transport data as tenant authority | Tenant clients validate host-selected scope before credentials/provider/DB effects | Host identity-mapping bugs remain external. |
| Cross-tenant lifecycle access | Missing/wrong transaction-local scope | Forced RLS, tenant-qualified keys/indexes | Administrative SQL roles bypass the guarantee. |
| SQL injection / generic tenant SQL | Application exposes arbitrary SQL | Parameterized package SQL; generic SQL is outside supported tenant boundary | Host must prevent injection and generic SQL authority. |
| Provider spoofing / oversized input | Untrusted network/provider response | HTTPS production destination policy, finite decode/download budgets, closed reviewed GET retry set | Payload validation does not prove provider authenticity. |
| Secret reflection / weak at-rest policy | Diagnostics expose values or operator mistakes compatibility mode for encryption | Bounded diagnostics; optional Fernet can be explicitly required | Default compatibility rows are not encrypted-at-rest proof; migration/rotation/custody remain external. |
| Restore into live cluster through alias | Different service labels resolve to same PostgreSQL cluster | Merged #228 verifier requires distinct exact service names and distinct caller-owned `pg_control_system().system_identifier` values | Caller may collect/misassociate identity evidence incorrectly; package does not authenticate the connection or authorize restore. |
| Unsafe or semantically incomplete restore | Command succeeds but target/catalog/application is wrong | Merged #212 bounds direct restore execution and archive metadata semantics; #228 bounds target cluster separation | Backup provenance, application/catalog acceptance, migration/key/WAL/PITR and RPO/RTO remain separate. |
| Checkpoint fork/replay | Concurrent consumers mutate same identity | PostgreSQL CAS/locking semantics | DB atomicity does not extend to provider/network effects. |
| Reconciliation overlap | Concurrent workers target same bounded identity | Tenant-qualified transient session advisory single-flight | Session lock is not durable leasing, scheduling, terminal retirement, or exactly-once. |
| Content-fidelity sabotage | Privacy layer silently rewrites authorized payload | Package paths preserve authorized content absent explicit policy | Host transformations require provenance and acceptance tests. |

## Explicit non-guarantees

- This document does not claim SOC 2, CSAP, ISO/IEC 27001, or another certification.
- RLS does not replace authentication, authorization, or SQL-injection prevention.
- Optional Fernet and redacted diagnostics do not prove all persisted secrets are encrypted or that key lifecycle/custody is solved.
- A receipt/hash does not prove backup provenance or restorability.
- A successful direct restore does not prove application readiness, PITR, or achieved recovery objectives.
- Distinct service names and `system_identifier` values prove only the bounded evidence supplied to the verifier differs; they do not authenticate connection provenance or authorize destructive recovery.
- Prefix checkpoints and session advisory locks are not distributed exactly-once guarantees.

## References

Joint Task Force. (2012). *Guide for conducting risk assessments* (NIST Special Publication 800-30, Revision 1). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-30r1

Joint Task Force. (2020). *Security and privacy controls for information systems and organizations* (NIST Special Publication 800-53, Revision 5). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-53r5

Scarfone, K., & Souppaya, M. (2016). *Guide to data-centric system threat modeling* (NIST Special Publication 800-154, Initial Public Draft). National Institute of Standards and Technology. https://csrc.nist.gov/pubs/sp/800/154/ipd

Swanson, M., Bowen, P., Phillips, A., Gallup, D., & Lynes, D. (2010). *Contingency planning guide for federal information systems* (NIST Special Publication 800-34 Rev. 1). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-34r1
