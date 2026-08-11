# Threat model

## Scope and maturity

This model covers pg-llm-batch as a standalone PostgreSQL-backed batch orchestration component and as a modular CWL service. Unless explicitly labelled **ACTIVE-PR**, controls described as implemented are **IMPLEMENTED-ON-PROTECTED-MAIN** at the documentation baseline. `SECURITY.md` remains authoritative for vulnerability reporting.

## Assets

- provider API credentials, encrypted secret values, and bootstrap Fernet key secret material;
- PostgreSQL configuration, request, batch, lifecycle, payload, and result metadata;
- prompt/request content stored for batch construction;
- remote provider identifiers and lifecycle evidence;
- bounded structured exception evidence used for diagnostics and reconciliation;
- package/release artifacts and provenance evidence;
- exact-source CI/review evidence used to decide whether code may reach protected main.

## Trust boundaries

1. **Caller/host → package API/CLI.** Caller-controlled strings, DSNs, provider identifiers, prompts, files, configuration, and structured error mappings are untrusted until validated or bounded by the public contract.
2. **Package → PostgreSQL.** PostgreSQL is the durable authority for package-owned state. Connection identity, RLS applicability, transaction ownership, and migration state are security boundaries.
3. **Package → provider HTTP endpoint.** The remote service and every response body/header/identifier are external and untrusted. Credentials authorize a request; they do not make provider output trusted application data.
4. **Repository source → CI/review control plane.** A PR source head, a GitHub synthetic merge ref, a live base branch, a check result, and an independent review are distinct evidence authorities.
5. **pg-llm-batch → CWL sibling services.** Sibling repositories are separate bounded contexts. Composition must use explicit interfaces rather than hidden cross-service application-database access.

## Threats and controls

| Threat | Boundary | Current control / target | Maturity |
| --- | --- | --- | --- |
| Credential disclosure through argv/logs or echoed prompt fallback | Caller/CLI | Database-backed `SecretStore.set_secret()` and `getpass` are IMPLEMENTED-ON-PROTECTED-MAIN primitives. ACTIVE-PR #93 guidance composes them into a documented manual prompt that promotes `getpass.GetPassWarning` to a hard failure, so when terminal echo control is unavailable it fails closed before accepting provider credential input. ACTIVE-PR #85 moves the equivalent CLI secret input off process argv and redacts rejected legacy argument values. | ACTIVE-PR #93 guidance over IMPLEMENTED-ON-PROTECTED-MAIN primitives / ACTIVE-PR #85 CLI |
| Bootstrap Fernet key disclosure through ambient process state | Host/bootstrap | `PG_LLM_BATCH_SECRET_KEY` is optional sensitive bootstrap secret material, distinct from database-backed provider credentials; deployment secret injection, scope, rotation, and environment exposure remain host responsibilities | IMPLEMENTED-ON-PROTECTED-MAIN boundary |
| Ambient environment or coercion silently changes explicit bootstrap authority | Bootstrap/config | Protected main exposes the current bootstrap/config interfaces but does not yet enforce the stronger exact-authority contract. ACTIVE-PR #89 requires an **explicit Postgres DSN** and an **explicit Fernet** bootstrap key to already be an **exact string** when supplied; a non-string explicit value fails before **environment fallback**, and only an omitted argument may consult the corresponding ambient bootstrap variable. An explicit DSN must be nonblank, while an explicit empty Fernet string intentionally suppresses ambient decryption authority. | IMPLEMENTED-ON-PROTECTED-MAIN baseline + ACTIVE-PR #89 hardening |
| Malformed persisted secret or wrong Fernet key leaks stored values or cryptography detail | DB→SecretStore | ACTIVE-PR #87 requires strict Base64 alphabet/padding and strict UTF-8 in the no-key path; malformed persistence becomes bounded `ConfigError`. A wrong Fernet key or invalid encrypted value also becomes bounded `ConfigError`, without retaining ciphertext or the underlying cryptography error through exception cause/context. Base64 remains obfuscation rather than encryption. | ACTIVE-PR #87 |
| Caller-owned mapping mutation rewrites structured exception evidence after construction | Caller/host → package error boundary | **ACTIVE-PR #105** takes a **shallow snapshot** of the outer caller-owned mapping at construction so later caller-side additions, removals, or replacements cannot rewrite package-owned outer evidence. Nested mutable values and direct mutation of the exception-owned public mapping remain possible, so the **live exception object** is **not an audit record** and must not be treated as immutable durable evidence. | ACTIVE-PR #105 |
| Operation failure span status is absent, leaks exception text, or telemetry status mutation masks the application failure | Package→telemetry | **ACTIVE-PR #106** sets operation **span status** to OpenTelemetry Error **without a description** on propagated failures while automatic exception recording remains disabled and **exception messages** stay out of telemetry. Success keeps status Unset, and ordinary **telemetry failure** during status construction or mutation cannot replace the application result or exception. | ACTIVE-PR #106 |
| Optional PostgreSQL monitoring creates persistent or privileged secondary copies of query content | PostgreSQL→operator/monitoring | **ACTIVE-PR #119** disables package-default persistent SQL statement/bind logging and `pg_stat_statements` collection/persistence while preserving purpose-bound database data. It explicitly treats `pg_stat_activity` **query text** as a bounded volatile residual while `track_activities` is enabled, and requires superuser/`pg_read_all_stats` visibility to remain least-privilege, purpose-bound, and auditable. | ACTIVE-PR #119 |
| Endpoint-agnostic model metadata or fail-open lookup failure selects the wrong tokenizer | PostgreSQL→tokenizer | **PLANNED #108** requires **endpoint-qualified** endpoint/model authority. A successful no-row result remains distinct from a **lookup failure**; failure must not silently activate **tokenizer fallback**, and bounded diagnostics must not copy lower-layer **exception text**, dynamic class names, DSNs, SQL, credentials, or unvalidated endpoint/model content. | PLANNED #108 |
| Durable lifecycle reservation/persistence failure exports dynamic exception identity or cause chain | Lifecycle→diagnostics | **PLANNED #125** replaces **dynamic exception** class names with a **finite** recovery vocabulary, distinguishes reservation from persistence, preserves only trusted validated identity/observation-order/**tenant scope** context, and prevents arbitrary lower-layer exception objects or text from surviving through exported `__cause__`/`__context__`. | PLANNED #125 |
| SSRF or unsafe provider destination | HTTP | Protected main **stringifies** the configured gateway value and **strips surrounding whitespace** before URL validation, then rejects remaining whitespace/control/backslash ambiguity, unsafe authority/query/fragment/ports, and non-loopback HTTP. `ACTIVE-PR` #71 tightens authority selection: a stringifiable non-string or leading/trailing whitespace/control/backslash fails **before secret lookup**; an accepted trailing slash is normalized only after exact validation. | IMPLEMENTED-ON-PROTECTED-MAIN normalization + ACTIVE-PR #71 exact-input hardening |
| Unbounded provider response memory/CPU | HTTP | bounded control responses and provider-file downloads; ACTIVE-PR #58 adds incremental result records | IMPLEMENTED-ON-PROTECTED-MAIN + ACTIVE-PR |
| Unsafe replay after response handoff | HTTP | acquisition retry is bounded; ACTIVE-PR #71 explicitly hardens post-handoff no-replay and transport classification | PARTIAL / ACTIVE-PR |
| Provider error or malformed successful payload is reflected into diagnostics/exception chains | HTTP | ACTIVE-PR #71 provider-error confidentiality classifies non-success operations from HTTP status before provider-body parsing and maps malformed successful UTF-8/JSON to fixed bounded diagnostics without retaining provider bytes/text or decoder/parser exceptions through exported cause/context. | ACTIVE-PR #71 |
| Parallel direct-SQL provider HTTP bypasses validated credential, destination, or remote-identity authority | PostgreSQL→provider | ACTIVE-PR #101 retires the legacy `pg_cron` + `pgsql-http` network path, which can use weaker database-visible secret material and a local batch UUID where a provider remote identity is required. Provider networking remains in `BatchAPIClient` / `DurableBatchAPIClient`. Issue #102 is the PLANNED bounded automatic-reconciliation replacement and must reuse that Python authority instead of recreating database HTTP. | ACTIVE-PR #101 retirement / PLANNED Issue #102 replacement |
| Malicious provider identifiers poison persistence/logging | HTTP→DB | strict resource identifier validation and bounded lifecycle metadata | IMPLEMENTED-ON-PROTECTED-MAIN |
| Cross-tenant durable-state disclosure | DB | Protected main is not yet tenant-qualified for remote lifecycle; #53 adds trusted tenant scope + forced RLS | ACTIVE-PR |
| Checkpoint corruption or competing consumer overwrite | DB | #60 adds tenant-qualified CAS checkpoint store, bounds and RLS | ACTIVE-PR |
| Audit evidence mutation | DB | #94 carries append-only audit table, forced RLS, UPDATE/DELETE/TRUNCATE rejection | ACTIVE-PR |
| Connection exhaustion through leaked owners | Package→DB | explicit owner cleanup exists in some paths; #87 closes remaining operation/construction lifetime gaps | ACTIVE-PR |
| Readiness endpoint leaks diagnostics or is resource-exhausted | Operator/HTTP | current health endpoint exists; #70 hardens redaction, timeout and concurrency. The same ACTIVE-PR validates the listener before socket creation: host is an exact non-empty string with no whitespace and no ASCII C0 control or DEL characters, and port is a non-boolean integer in `1..65535`. | ACTIVE-PR #70 |
| Environment-controlled health-port text becomes shell command syntax before application validation | Container command authority | ACTIVE-PR #70 removes `PG_LLM_BATCH_HEALTH_PORT` from the executable image command path and requires **exec-form** JSON for the readiness server and healthcheck at fixed default port `8080`; a custom port requires an explicit coordinated command/healthcheck override rather than shell expansion. | ACTIVE-PR #70 |
| Standalone deployment unexpectedly exposes another host service/port | Compose/host network | ACTIVE-PR #91 binds the complete host-published service allow-list to loopback PostgreSQL TCP 5432 and component TCP 8080, each once; a third published service or extra port fails the contract. | ACTIVE-PR #91 |
| Release artifact TOCTOU or substitution | Build/release | #57 carries descriptor-pinned reproducibility and artifact-identity checks | ACTIVE-PR |
| CI accepts evidence from wrong commit | GitHub control plane | #88 binds CI checkout/verification to exact source head | ACTIVE-PR |
| Model/reviewer outage is misreported as source defect | Review plane | Evidence classes are kept distinct by governance docs; infrastructure failure must not be synthesized into a code finding | ACCEPTED-ARCHITECTURE |
| Competing autonomous writers overwrite work | Repository write plane | branch-local writer lease, pre-write refetch, no force push, work rotation | ACCEPTED-ARCHITECTURE / ACTIVE-PR documentation |

## Privacy and data governance

The package may handle prompts, responses, provider metadata, operational identifiers, and structured exception evidence that can contain personal or confidential information. Default risk treatment is purpose-bound authorization, least privilege, tenant/service identity, encryption in transit and for secret material, bounded retention/export decisions owned by the deployment, and minimal diagnostics. Blanket masking is not a substitute for authorization and can destroy batch utility. Provider response text must not be copied into logs or telemetry merely to aid debugging. ACTIVE-PR #71 extends that rule to malformed successful provider payloads and exported exception cause/context; ACTIVE-PR #87 applies the same bounded-diagnostic principle to malformed stored secrets and wrong Fernet keys.

ACTIVE-PR #105 reduces alias-driven drift in the outer structured exception mapping but does not create immutable or durable audit evidence. A live exception object must not be retained as an audit system merely because the original caller-owned outer mapping was snapshotted. Hosts that require durable evidence must serialize a separately bounded, authorized, retained representation and must decide how nested content is classified.

ACTIVE-PR #106 keeps exception messages, provider bodies, identifiers, and stack traces out of span status descriptions/events while making failure spans queryable through description-free Error status. Success remains Unset. An ordinary telemetry failure while constructing or applying that status is isolated from the application result.

ACTIVE-PR #119 applies the same purpose-bound approach to PostgreSQL monitoring. Persistent SQL statement/bind logging and `pg_stat_statements` query-text retention are disabled in the optional example by default, but `track_activities` intentionally leaves a bounded volatile `pg_stat_activity` query-text surface for diagnosis. That surface remains sensitive live data; privileged `pg_read_all_stats`/superuser visibility is a deployment authorization and access-audit boundary, not an excuse to claim content-free telemetry. Disabling `track_activities` is permitted only as an explicit operability/privacy tradeoff.

PLANNED #108 makes tokenizer metadata lookup itself a trust boundary: operational lookup failure is not authoritative absence and cannot silently grant fallback authority. PLANNED #125 applies the same confidentiality rule to durable lifecycle recovery evidence by replacing dynamic exception identity and cause chains with a finite package vocabulary while preserving only trusted reconciliation context.

## Fail-closed rules

- malformed identifiers, unsafe destinations, impossible bounds, unsupported migration state, stale checkpoint evidence, or authorization ambiguity fail closed;
- under ACTIVE-PR #89, a non-string **explicit Postgres DSN** or **explicit Fernet** bootstrap key fails before **environment fallback**; only omitted values may consult ambient bootstrap sources, while an explicit empty Fernet string suppresses ambient decryption authority;
- under ACTIVE-PR #71, a gateway destination that is not already an exact string, has surrounding whitespace/control/backslash ambiguity, or otherwise fails the stricter authority grammar is rejected before secret lookup; trailing-slash normalization occurs only after exact validation;
- malformed readiness listener hosts—including ASCII C0 control or DEL characters—or non-boolean/non-integer/out-of-range ports fail before socket creation under ACTIVE-PR #70;
- the ACTIVE-PR #70 container boundary keeps readiness server and healthcheck execution in exec-form JSON at port 8080 and never evaluates `PG_LLM_BATCH_HEALTH_PORT` through a shell; custom ports require explicit deployment overrides;
- a standalone Compose host-publication outside the ACTIVE-PR #91 allow-list fails rather than broadening exposure silently;
- a secret-entry path that cannot guarantee hidden terminal input must fail before accepting the provider credential rather than falling back to visible input;
- malformed no-key Base64/UTF-8 persistence and wrong Fernet keys remain bounded `ConfigError` paths under ACTIVE-PR #87, not fallback-decryption opportunities;
- under ACTIVE-PR #101, the legacy SQL retriever is removed rather than repaired into a second provider network authority; Issue #102 may restore automation only through validated provider remote identity and the Python credential/destination boundary;
- under ACTIVE-PR #105, the package snapshots only the outer caller-owned error mapping; callers and operators must not infer deep immutability, append-only provenance, or durable audit authority from that boundary;
- under ACTIVE-PR #106, operation failure span status is best-effort telemetry; telemetry failure cannot replace an application result or exception, and no exception message is promoted into status description authority;
- under ACTIVE-PR #119, disabling persistent query-content copies does not authorize calling the database monitoring plane content-free while `pg_stat_activity` can expose current/recent query text; privileged access must remain explicitly governed;
- under PLANNED #108, a tokenizer metadata **lookup failure** must not silently become "no matching metadata" or activate tokenizer fallback, and failure diagnostics must exclude arbitrary exception text;
- under PLANNED #125, durable lifecycle reservation/persistence failures must not export dynamic exception class names or retain arbitrary lower-layer failures through `__cause__` or `__context__`;
- a missing/queued/cancelled/stale required check is not success;
- a status/comment/model message is not an independent formal approval;
- a synthetic merge ref is not interchangeable with the exact contributor head;
- an ACTIVE-PR control is not a protected-main guarantee.

## Recovery and rollback

Security changes require an explicit rollback or recovery path in the owning ADR/doctoring. Rollback must never silently erase durable evidence or weaken a trust boundary. For database changes, use reviewed forward/rollback migrations and protect non-empty evidence stores. For CI/review changes, revert to the last known protected-main workflow only if doing so preserves exact-source identity, least privilege, and required-gate semantics.

For ACTIVE-PR #105, rollback means restoring the previously reviewed exception-construction semantics and reclassifying affected documentation/tests; it must not reinterpret already emitted mutable exception objects as trustworthy historical audit evidence.

For ACTIVE-PR #106, rollback restores the prior status-unset failure-span behavior while retaining automatic exception recording suppression, bounded attributes, and telemetry failure isolation; it must not introduce descriptions or exception recording as a shortcut.

For ACTIVE-PR #119, a deployment that requires content-bearing SQL audit evidence should use a deployment-owned overlay with explicit scope/access/retention controls rather than restoring blanket logging to the package default. Accidental query-content logging requires containment and credential rotation where relevant; disabling live activity tracking must be treated separately because it removes diagnostic capability.

For PLANNED #108/#125, rollback/recovery must preserve the previous authoritative data and durable ordering semantics rather than restoring fail-open lookup ambiguity or leaking lower-layer exception evidence as an operational shortcut.

## Verification

Security acceptance combines deterministic tests, live PostgreSQL integration where persistence is involved, SAST/dependency/security checks, exact-head workflow identity, independent review where required, and protected-main operational evidence for control-plane changes. For #105, verification must prove outer caller-alias isolation, absent-response handling, coverage, and the documented non-immutability boundary. For #106, verification must prove description-free Error status for propagated failures, success status Unset, exception-message confidentiality, and isolation of optional trace-status API or span-status mutation failures. For #119, verification must prove persistent server logging/query-statistics defaults do not copy SQL or bind values while the residual `pg_stat_activity` query-text and privileged-access boundary remains explicit. For #108, verification must prove endpoint-qualified selection, explicit no-row versus lookup-failure behavior, confidential bounded diagnostics, and deterministic fallback only after authoritative absence. For #125, verification must prove reservation/persistence separation, finite failure categories, trusted tenant/lifecycle context, and absence of lower-layer exception text or cause/context leakage. No one channel substitutes for the others.
