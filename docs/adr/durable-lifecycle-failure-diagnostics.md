# ADR: Bounded durable lifecycle failure diagnostics

- **Status:** PLANNED — Issue #125
- **Implementation dependency:** protected integration or proven successor of tenant lifecycle PR #53
- **Documentation authority:** ACTIVE-PR #93

## Context

Protected `main` reserves durable observation order before provider I/O and records provider-success/persistence-failure evidence for reconciliation. The generic failure paths in `DurableBatchAPIClient._reserve_observation_order()` and `_persist_snapshot()` currently derive `response_data.error_type` from `type(exc).__name__` and chain arbitrary lower-layer exceptions through `GatewayError.__cause__`.

That behavior creates two related risks. A caller-supplied reserver/recorder or database layer can introduce a dynamic exception class name into exported recovery evidence, making a supposedly bounded diagnostic field high-cardinality and implementation-dependent. The chained exception can also retain arbitrary lower-layer exception text or state after the package has already translated the failure into its public error boundary. This is distinct from provider-transport confidentiality work in #71 and from the shallow structured-evidence ownership boundary in #105.

The tenant-qualified lifecycle branch #53 owns the same production surface and adds trusted tenant recovery context. A competing main-based implementation would invalidate the active stack and risk losing that context, so #125 remains PLANNED until #53 is protected-main integrated or superseded by a proven replacement.

## Decision drivers

- keep durable lifecycle recovery evidence useful for reconciliation without exporting arbitrary implementation detail;
- preserve the semantic difference between reservation failure before provider I/O and persistence failure after a successful provider effect;
- keep error categories finite, low-cardinality, and independent of injected implementation class names;
- prevent credentials, DSNs, SQL/provider content, and arbitrary lower-layer exception text from surviving in exported error chains;
- preserve trusted operation, phase, validated identity, observation order, and tenant scope where available;
- preserve process-level control-flow behavior unless a separate reviewed isolation contract says otherwise; and
- avoid racing #53 or weakening durable ordering/RLS semantics.

## Alternatives considered

### A. Keep `type(exc).__name__` and chained exceptions for debugging

Rejected. Dynamic exception names are not a bounded public vocabulary, and retaining arbitrary lower-layer exceptions can preserve sensitive implementation state. Debuggability is not sufficient justification for exporting uncontrolled error authority.

### B. Replace every failure with one opaque message and no reconciliation fields

Rejected. Operators need trusted bounded phase/operation/identity/order context to distinguish a pre-provider reservation failure from a post-provider persistence failure and to reconcile side effects safely.

### C. Define finite lifecycle failure categories and suppress uncontrolled exception chains

Chosen. The package will retain only trusted bounded reconciliation fields and a finite failure category. Generic lower-layer failures will not survive through exported `__cause__` or `__context__`; package-defined validation failures may retain only explicitly reviewed bounded fields.

## Decision

1. Issue #125 owns the PLANNED durable lifecycle failure-diagnostic hardening.
2. Reservation and persistence failures use a finite documented category vocabulary; arbitrary **dynamic exception** class names are not exported diagnostic authority.
3. Exported `GatewayError` messages/details and exception `__cause__` / `__context__` must not retain DSNs, credentials, SQL/provider payloads, arbitrary lower-layer exception text, or injected exception objects.
4. Recovery evidence may retain the trusted operation and phase, validated endpoint alias and provider batch identifier when available, reserved observation order when one exists, and trusted tenant scope on tenant-qualified clients.
5. Reservation failure must remain observably before provider I/O. Persistence failure after a successful provider effect must continue to communicate that the remote effect can require reconciliation.
6. Ordinary exceptions are translated at the package boundary without swallowing process-level control-flow exceptions that are outside the reviewed catch contract.
7. Implementation occurs from protected #53 or a proven successor. No predecessor check/review evidence transfers.

## Security and privacy impact

This design follows selective disclosure rather than blanket masking: reconciliation keeps the minimum trusted identifiers and phase data required for recovery while removing uncontrolled implementation detail. It is intended to reduce CWE-209-style error-message disclosure and high-cardinality diagnostics. It does not claim that all exception objects are audit records or that package diagnostics substitute for deployment access control and retention policy.

## Compatibility and migration

No persistence or ERD change is implied. The primary compatibility change is diagnostic: consumers must not depend on arbitrary Python exception class names or chained lower-layer exception objects as a supported contract. Stable package-domain fields remain the compatibility surface. Tenant-qualified implementations must preserve #53's trusted tenant recovery context.

## Verification and acceptance

Implementation must be test-first and include:

- custom reserver/recorder/database exceptions whose class names and messages contain secret-like sentinels;
- proof that sentinels cannot escape through `str(error)`, `repr(error)`, structured response data, `__cause__`, or `__context__`;
- reservation-failure tests proving zero provider I/O;
- persistence-failure tests proving the provider effect is not misreported as absent and bounded reconciliation context survives;
- standalone and tenant-qualified lifecycle clients;
- process-level control-flow regressions;
- Python 3.10, 3.12, and 3.14;
- exact 100% owned production statement/branch coverage and public docstrings; and
- security, SAST, package, provenance, exact-source, and live-policy gates on the unchanged final head.

## Failure, recovery, and rollback

If category translation itself fails, fail closed without falling back to the original exception message or dynamic class name. Recovery uses the retained trusted phase/identity/order/tenant fields plus external provider/database evidence. Rollback may restore the prior package implementation only if it does not reintroduce uncontrolled exception disclosure; otherwise roll forward with a corrected finite classifier.

## References

MITRE. (2026). *CWE-209: Generation of error message containing sensitive information (Version 4.20).* https://cwe.mitre.org/data/definitions/209.html

National Institute of Standards and Technology. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST SP 800-218). https://doi.org/10.6028/NIST.SP.800-218
