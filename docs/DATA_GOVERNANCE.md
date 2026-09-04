# Data governance

## Authority

This contract maps protected-main data classes, owners, tenant authority,
retention, deletion, and privacy boundaries. SQL, package code, and the
canonical PRD/TRD remain stronger authority. It is evidence readiness, not a
certification and not a claim that a deployment has a complete records program.

## What to do next

1. Decide which host identity is allowed to select `tenant_scope` before any
   package call.
2. Do not mask, tokenize away, or truncate authorized business payloads inside
   this package. If your policy requires transformation, do it in an explicit
   host boundary with provenance and acceptance tests.
3. Keep Fernet or an external secret manager as a host/deployment choice.
   Protected main can persist `com_secrets.is_encrypted = FALSE` in
   compatibility mode.
4. Own backup copies, replica retention, log/telemetry retention, and
   destructive deletion yourself. The package will not invent a general purge.
5. Use `standalone` for a single-tenant operator. Do not reuse that scope as an
   anonymous public bucket.

## Data classes

| Class | Principal objects | Owner | Package duty |
| --- | --- | --- | --- |
| Authorized business payloads | `llm_requests` prompts/results, `llm_batch_file_payloads`, `llm_jsonl_lines` | Embedding host / business process | Persist and replay exactly. Do not mask. |
| Durable lifecycle projection | `llm_remote_batch_jobs` | Host-selected `tenant_scope` plus package recorder | Tenant-qualify identity, bind `set_config`, force RLS. |
| Result checkpoints | `llm_result_stream_checkpoints` | Host-selected consumer name plus tenant | Store prefix evidence only. |
| Standalone configuration | `com_config` | Operator | Key/value settings. Not tenant authorization. |
| Standalone secrets | `com_secrets` | Operator / secret-manager host | Optional Fernet. Compatibility plaintext is not a production claim. |
| Provider credentials | Host credential provider | Deployment | Resolve after tenant validation. Never tenant-keyed by this package. |
| Recovery evidence | Receipts, artifact hashes, schema hashes | Operator | Content-free identity. Not restorability. |
| Operational diagnostics | Errors, logs, readiness, telemetry | Package | Omit payloads, DSNs, credentials, and dynamic exception text. |

## Tenant authority

`tenant_scope` is selected only by a trusted authenticated/authorized host
boundary. Provider metadata, remote identifiers, request bodies, model output,
endpoint aliases, and transport headers are never tenant authorities. The
embedding host owns the identity-to-tenant map.

## Retention and deletion

Protected main does not define a universal business-data retention duration.
The embedding host owns purpose, retention period, deletion authorization, and
evidence that the policy ran. The deployment owner separately owns PostgreSQL
backup/replica, WAL, and infrastructure log retention. Provider-side retention
remains a provider/account policy unless a reviewed adapter implements it.

The package will not silently delete unknown operator objects, rewrite history,
or `CASCADE` through unrelated schemas as a recovery shortcut.

## Privacy without paralysis

ISO/IEC 29100 treats purpose specification and data minimization as
organization policy, not as an excuse to destroy the meaning of a processing
record (ISO/IEC, 2024). NIST SP 800-53 Revision 5 likewise places confidentiality
controls at authorization, access, transmission, and audit boundaries (Joint
Task Force, 2020). This package therefore:

- preserves authorized business payloads;
- redacts operational surfaces;
- fails closed on untrusted provider and path input;
- refuses to treat RLS or diagnostic redaction as proof that persisted
  business content was masked.

## References

International Organization for Standardization. (2024). *Information
technology — Security techniques — Privacy framework* (ISO/IEC 29100:2024).
https://www.iso.org/standard/85938.html

Joint Task Force. (2020). *Security and privacy controls for information systems
and organizations* (NIST Special Publication 800-53, Revision 5). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-53r5
