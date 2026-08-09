# Threat model

## Scope and maturity

This model covers pg-llm-batch as a standalone PostgreSQL-backed batch orchestration component and as a modular CWL service. Unless explicitly labelled **ACTIVE-PR**, controls described as implemented are **IMPLEMENTED-ON-PROTECTED-MAIN** at the documentation baseline. `SECURITY.md` remains authoritative for vulnerability reporting.

## Assets

- provider API credentials, encrypted secret values, and bootstrap Fernet key secret material;
- PostgreSQL configuration, request, batch, lifecycle, payload, and result metadata;
- prompt/request content stored for batch construction;
- remote provider identifiers and lifecycle evidence;
- package/release artifacts and provenance evidence;
- exact-source CI/review evidence used to decide whether code may reach protected main.

## Trust boundaries

1. **Caller/host → package API/CLI.** Caller-controlled strings, DSNs, provider identifiers, prompts, files, and configuration are untrusted until validated.
2. **Package → PostgreSQL.** PostgreSQL is the durable authority for package-owned state. Connection identity, RLS applicability, transaction ownership, and migration state are security boundaries.
3. **Package → provider HTTP endpoint.** The remote service and every response body/header/identifier are external and untrusted. Credentials authorize a request; they do not make provider output trusted application data.
4. **Repository source → CI/review control plane.** A PR source head, a GitHub synthetic merge ref, a live base branch, a check result, and an independent review are distinct evidence authorities.
5. **pg-llm-batch → CWL sibling services.** Sibling repositories are separate bounded contexts. Composition must use explicit interfaces rather than hidden cross-service application-database access.

## Threats and controls

| Threat | Boundary | Current control / target | Maturity |
| --- | --- | --- | --- |
| Credential disclosure through argv/logs or echoed prompt fallback | Caller/CLI | Database-backed secrets; the documented protected-main-compatible manual prompt promotes `getpass.GetPassWarning` to a hard failure, so when terminal echo control is unavailable it fails closed before accepting provider credential input; ACTIVE-PR #85 moves the equivalent CLI secret input off process argv and redacts rejected legacy argument values | IMPLEMENTED-ON-PROTECTED-MAIN manual path / ACTIVE-PR CLI |
| Bootstrap Fernet key disclosure through ambient process state | Host/bootstrap | `PG_LLM_BATCH_SECRET_KEY` is optional sensitive bootstrap secret material, distinct from database-backed provider credentials; deployment secret injection, scope, rotation, and environment exposure remain host responsibilities | IMPLEMENTED-ON-PROTECTED-MAIN boundary |
| Ambient environment silently overrides explicit authority | Bootstrap/config | Current explicit configuration interfaces; ACTIVE-PR #89 distinguishes omitted from explicitly blank values | ACTIVE-PR hardening |
| SSRF or unsafe provider destination | HTTP | URL normalization, HTTPS except explicit loopback, bounded resource identifiers, no query/fragment/userinfo in governed base URL | IMPLEMENTED-ON-PROTECTED-MAIN |
| Unbounded provider response memory/CPU | HTTP | bounded control responses and provider-file downloads; ACTIVE-PR #58 adds incremental result records | IMPLEMENTED-ON-PROTECTED-MAIN + ACTIVE-PR |
| Unsafe replay after response handoff | HTTP | acquisition retry is bounded; ACTIVE-PR #71 explicitly hardens post-handoff no-replay and transport classification | PARTIAL / ACTIVE-PR |
| Malicious provider identifiers poison persistence/logging | HTTP→DB | strict resource identifier validation and bounded lifecycle metadata | IMPLEMENTED-ON-PROTECTED-MAIN |
| Cross-tenant durable-state disclosure | DB | Protected main is not yet tenant-qualified for remote lifecycle; #53 adds trusted tenant scope + forced RLS | ACTIVE-PR |
| Checkpoint corruption or competing consumer overwrite | DB | #60 adds tenant-qualified CAS checkpoint store, bounds and RLS | ACTIVE-PR |
| Audit evidence mutation | DB | #94 carries append-only audit table, forced RLS, UPDATE/DELETE/TRUNCATE rejection | ACTIVE-PR |
| Connection exhaustion through leaked owners | Package→DB | explicit owner cleanup exists in some paths; #87 closes remaining operation/construction lifetime gaps | ACTIVE-PR |
| Readiness endpoint leaks diagnostics or is resource-exhausted | Operator/HTTP | current health endpoint exists; #70/#91 harden redaction, timeout, concurrency and listener exposure | ACTIVE-PR |
| Release artifact TOCTOU or substitution | Build/release | #57 carries descriptor-pinned reproducibility and artifact-identity checks | ACTIVE-PR |
| CI accepts evidence from wrong commit | GitHub control plane | #88 binds CI checkout/verification to exact source head | ACTIVE-PR |
| Model/reviewer outage is misreported as source defect | Review plane | Evidence classes are kept distinct by governance docs; infrastructure failure must not be synthesized into a code finding | ACCEPTED-ARCHITECTURE |
| Competing autonomous writers overwrite work | Repository write plane | branch-local writer lease, pre-write refetch, no force push, work rotation | ACCEPTED-ARCHITECTURE / ACTIVE-PR documentation |

## Privacy and data governance

The package may handle prompts, responses, provider metadata, and operational identifiers that can contain personal or confidential information. Default risk treatment is purpose-bound authorization, least privilege, tenant/service identity, encryption in transit and for secret material, bounded retention/export decisions owned by the deployment, and minimal diagnostics. Blanket masking is not a substitute for authorization and can destroy batch utility. Provider response text must not be copied into logs or telemetry merely to aid debugging.

## Fail-closed rules

- malformed identifiers, unsafe destinations, impossible bounds, unsupported migration state, stale checkpoint evidence, or authorization ambiguity fail closed;
- a secret-entry path that cannot guarantee hidden terminal input must fail before accepting the provider credential rather than falling back to visible input;
- a missing/queued/cancelled/stale required check is not success;
- a status/comment/model message is not an independent formal approval;
- a synthetic merge ref is not interchangeable with the exact contributor head;
- an ACTIVE-PR control is not a protected-main guarantee.

## Recovery and rollback

Security changes require an explicit rollback or recovery path in the owning ADR/doctoring. Rollback must never silently erase durable evidence or weaken a trust boundary. For database changes, use reviewed forward/rollback migrations and protect non-empty evidence stores. For CI/review changes, revert to the last known protected-main workflow only if doing so preserves exact-source identity, least privilege, and required-gate semantics.

## Verification

Security acceptance combines deterministic tests, live PostgreSQL integration where persistence is involved, SAST/dependency/security checks, exact-head workflow identity, independent review where required, and protected-main operational evidence for control-plane changes. No one channel substitutes for the others.
