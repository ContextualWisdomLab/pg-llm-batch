# Threat model

## Authority

This model describes protected-main `pg-llm-batch` assets, trust boundaries,
attacker capabilities, package mitigations, and residual risk. It is evidence
readiness for SOC 2 / CSAP preparation. It is not a certification, a penetration
test, or a claim that a deployment is authorized for production.

Use it to decide the next host control, not to infer that PostgreSQL row-level
security, recovery receipts, or redacted diagnostics have already closed a
business risk.

The methodology follows data-centric threat modeling (Scarfone & Souppaya,
2016/2016 IPD) and the NIST risk-assessment process (Joint Task Force, 2012):
identify the data, the system where it lives, the relevant threat sources, the
preconditions those sources need, and the residual risk after package controls.
Control families are aligned to NIST SP 800-53 Revision 5 (Joint Task Force,
2020).

## What to do next

1. Keep tenant selection behind your authenticated and authorized host boundary.
2. Do not grant arbitrary SQL, `SUPERUSER`, or `BYPASSRLS` to the application
   role that runs this package.
3. Preserve authorized business payloads. Do not add blanket PII masking on
   prompts, JSONL, or provider results; that would change token counts, replay,
   and downstream decisions.
4. Treat recovery receipts and artifact hashes as identity evidence only. They
   do not prove a backup is restorable or that a restore target is isolated.
5. Run `standalone` when you are a single-tenant operator. Use
   `TenantDurableBatchAPIClient` only after your host has already chosen
   `tenant_scope`.

## Assets

| Asset | Where it lives | Why a buyer cares |
| --- | --- | --- |
| Authorized prompts, JSONL payloads, and provider results | `llm_requests`, `llm_batch_file_payloads`, `llm_jsonl_lines`, provider files | Business meaning. Silent masking or truncation invalidates accounting. |
| Durable remote lifecycle identity | `llm_remote_batch_jobs` keyed by `(tenant_scope, endpoint_alias, remote_batch_id)` | Prevents one tenant from observing or advancing another tenant's batch. |
| Result-stream checkpoints | `llm_result_stream_checkpoints` keyed by `(tenant_scope, checkpoint_consumer_name, endpoint_alias, remote_batch_id)` | Prefix resume only. Not provider authenticity or whole-stream immutability. |
| Standalone secrets and configuration | `com_secrets`, `com_config` | Bootstrap transport. Compatibility mode can still persist `is_encrypted = FALSE`. |
| Provider credentials | Host-injected credential provider or standalone secret store | Never a tenant-selected authority and never a telemetry attribute. |
| Recovery evidence | In-memory receipts plus caller-owned backup/schema bytes | Content-free hash/size identity. Not restorability. |

## Trust boundaries

```text
[Caller / operator]
        |  host authentication and authorization (out of package)
        v
[Host control plane] -- selects tenant_scope, credentials, DSN, restore target
        |  package Python API / CLI only
        v
[pg-llm-batch] -- validates, bounds I/O, binds transaction-local set_config
        |  parameterized SQL
        v
[PostgreSQL] -- forced RLS for lifecycle and checkpoint tables
        |
        +--> [Provider Batch API] untrusted statuses, IDs, JSON, JSONL
        +--> [Caller-owned backup/restore tools] untrusted until a shipped executor lands
```

The package does not authenticate callers. `tenant_scope` is routing context
written with parameterized `set_config('pg_llm_batch.tenant_scope', ..., true)`.
A role that can execute arbitrary SQL can choose any scope. RLS is defense in
depth after that trusted write.

## Threat sources and package mitigations

| Threat source | Needed precondition | Package mitigation on protected main | Residual risk |
| --- | --- | --- | --- |
| Confused-deputy tenant selection | Host accepts provider IDs, headers, or model output as tenant authority | Tenant clients reject that path; scope is validated before reservation, credentials, provider I/O, or lifecycle SQL | Host mapping bugs remain outside the package. |
| Cross-tenant lifecycle read/write | Application role plus missing or wrong transaction-local scope | Forced RLS default-deny; tenant-qualified unique key and status index | `SUPERUSER` / `BYPASSRLS` / arbitrary SQL bypass the guarantee. |
| SQL injection or generic tenant SQL | Application role exposed through a SQL console | Parameterized statements; documented prohibition on generic SQL | The custom setting is not a credential. Do not grant arbitrary SQL. |
| Provider spoofing or oversized bodies | Network path to an unvalidated URL or unbounded parser | HTTPS production destinations, finite decoded-byte budgets, closed GET retry set `{408, 425, 429, 502, 503, 504}` | Provider authenticity is not proved by payload validation. HTTP 500 and POST stay single-attempt. |
| Secret reflection | Diagnostics copy DSNs, keys, prompts, or provider bodies | Bounded error vocabularies; public readiness omits lower-layer text | Generic `ValidationError` rejected-value confidentiality is still an active overlay. |
| Backup theft or unsafe restore | Operator points restore at the live cluster or a guessed artifact | Receipts and hashes identify bytes; they do not execute dump/restore | Executable backup/restore, catalog acceptance, and authenticated target isolation remain unshipped. |
| Checkpoint fork or replay | Concurrent consumers advance the same identity | CAS `SELECT ... FOR UPDATE` with exact previous checkpoint | PostgreSQL atomicity does not extend to provider or network effects. |
| Content-fidelity sabotage | A privacy filter rewrites authorized payloads | Package paths preserve authorized content unless a reviewed host policy says otherwise | A host that transforms content must keep provenance and acceptance tests. |

## Explicit non-guarantees

- This document does not claim SOC 2, CSAP, ISO/IEC 27001, or any other
  certification.
- RLS does not replace authentication, authorization, or SQL-injection
  prevention.
- A recovery receipt, schema hash, or backup-artifact hash does not prove
  restorability, live-cluster parity, PITR, RPO, RTO, HA, or DR.
- A prefix checkpoint is not a distributed exactly-once claim.
- `standalone` is an explicit single-tenant scope, not an anonymous public mode.

## References

Joint Task Force. (2012). *Guide for conducting risk assessments* (NIST Special
Publication 800-30, Revision 1). National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-30r1

Joint Task Force. (2020). *Security and privacy controls for information systems
and organizations* (NIST Special Publication 800-53, Revision 5). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-53r5

Scarfone, K., & Souppaya, M. (2016). *Guide to data-centric system threat
modeling* (NIST Special Publication 800-154, Initial Public Draft). National
Institute of Standards and Technology.
https://csrc.nist.gov/pubs/sp/800/154/ipd
