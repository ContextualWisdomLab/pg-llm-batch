# Provider-secret encryption deployment policy

- **Status:** PLANNED — Issue #121
- **Documentation maturity:** ACTIVE-PR #93
- **Implementation maturity:** not implemented on protected `main`
- **Decision owner:** pg-llm-batch secret/configuration boundary after #85/#87/#89 settle

## Context

Protected `main` supports Fernet encryption for `SecretStore` only when a Fernet key is supplied. Without that key, provider secrets are stored as Base64 text with `is_encrypted = FALSE`; the implementation warns that this mode is for local/development use. Base64 is reversible encoding and **not encryption**. A warning and a class docstring do not create a machine-enforced deployment boundary, so a deployment can accidentally omit the key and continue to persist provider credentials in the weaker development representation.

Issue #121 tracks the missing policy boundary. It is intentionally separate from #85, which owns secret input outside process argv; #87, which owns connection/resource cleanup plus malformed stored-secret and wrong-key failure behavior; and #89, which owns exact explicit-versus-ambient bootstrap-key precedence. No evidence from those branches transfers to this planned decision.

## Drivers

- make at-rest provider-secret confidentiality an explicit deployment choice rather than an accidental consequence of a missing key;
- retain a deliberate local/development mode without misrepresenting Base64 as confidentiality;
- fail before persistence when an operator selects **encryption-required** operation but usable encryption authority is unavailable;
- preserve standalone and embedding-host interoperability instead of requiring ContextualWisdomLab-specific key infrastructure;
- provide safe migration and **key rotation** paths for existing durable secrets;
- keep diagnostics, readiness, migration evidence, and recovery metadata free of plaintext provider credentials, ciphertext, DSNs, and key material; and
- improve CSAP/SOC 2 evidence readiness without claiming certification.

## Considered alternatives

### A. Keep the warning-only Base64 fallback everywhere

Rejected for commercial deployments. The current fallback is useful for deliberate development, but a warning cannot prove that a production operator intended to accept reversible storage.

### B. Remove Base64 support and require Fernet unconditionally

Rejected as the immediate design. It would break an explicitly documented local/development path and could strand existing `is_encrypted = FALSE` rows without a migration. Embedded callers may also supply credentials through their own provider boundary rather than the package-owned store.

### C. Infer production from environment names, hostnames, or network topology

Rejected. Deployment purpose is authority selected by the operator/embedding host; guessing it from `ENV`, DNS, Compose names, or public/private addressing is brittle and unsafe.

### D. Add an explicit storage policy with migration and rotation semantics

Chosen. The package should expose an explicit mode that separates deliberate development obfuscation from encryption-required operation while keeping key custody and deployment authorization outside the package unless a later ADR deliberately moves those responsibilities.

## Decision

Issue #121 shall implement an explicit provider-secret storage policy after the overlapping #85/#87/#89 surfaces are protected-main integrated or replaced.

1. The policy has a deliberate development/obfuscation mode and an **encryption-required** mode. Selection is explicit; the package must not infer the mode from deployment names or topology.
2. In encryption-required mode, a missing Fernet key, unavailable cryptography implementation, malformed key, or any attempted Base64 write fails before provider-secret persistence. Errors use fixed, bounded diagnostics and do not retain plaintext, ciphertext, DSNs, or underlying cryptography exceptions as exported secret-bearing evidence.
3. Development mode may preserve the current Base64 representation only as an explicit compatibility path. Documentation and operator/readiness evidence must call it obfuscation, **not encryption**.
4. Transitioning a database to encryption-required mode must inspect existing `is_encrypted = FALSE` rows before enforcement. The migration either re-encrypts those rows atomically under reviewed key authority or fails closed without destroying recoverable data. An interrupted migration must have deterministic restart/rollback guidance.
5. Key rotation is explicit and bounded. If `MultiFernet` or an equivalent key-ring design is selected, new writes use one active key, previous keys are decrypt-only during a bounded transition, stored values are rotated under controlled migration, and an old key is retired only after evidence proves no supported row still requires it. The package must not create an unbounded ambient key list.
6. Readiness/operability may expose finite policy state such as `development-obfuscation`, `encryption-required-ready`, or a fixed failure category, but never provider values, encrypted values, key material, credential-bearing DSNs, or dynamic exception text.
7. Embedding hosts may continue to provide credentials through the documented credential-provider seam without using `SecretStore`. This ADR does not make the package-owned database store mandatory.
8. Business authorization, key custody, rotation approval, retention, erasure/export, backup expiry, residency, and privileged-access governance remain deployment/host responsibilities unless a later accepted decision explicitly moves an authority boundary.

## Consequences and non-goals

The planned policy prevents accidental downgrade from encryption-required operation to reversible Base64 storage. It does not make Fernet equivalent to a managed KMS/HSM, prove key custody, authenticate users, authorize a workload to a tenant, define business retention, or establish regulatory certification. Encryption at rest is one control inside a wider authorization, access, backup, recovery, and audit model.

This decision does not change protected-main behavior until Issue #121 is implemented and integrated. It does not modify the CLI secret-input contract in #85, stored-secret parsing/resource ownership in #87, or bootstrap precedence in #89.

## Failure and recovery

- Missing/invalid encryption authority in encryption-required mode fails before new persistence.
- Existing unencrypted rows block activation until the reviewed migration succeeds or the operator deliberately remains in development mode.
- Rotation failure leaves the previously proven decrypt set available until migration state is reconciled; retirement of an old key is never inferred from elapsed time alone.
- A migration or rotation must preserve database transaction/restart semantics and must not erase the only decryptable representation before the replacement is durably verified.
- Rollback may restore the previous accepted policy/key set only if doing so preserves access to existing encrypted rows and does not silently downgrade an encryption-required deployment to Base64 writes.

## Verification and acceptance

Implementation acceptance requires realistic PostgreSQL tests for fresh encrypted writes, deliberate development Base64 writes, missing/wrong/malformed key refusal, unavailable cryptography refusal where testable, existing-unencrypted-row discovery, successful atomic re-encryption, interrupted migration and restart/rollback, bounded key rotation, old-key retirement proof, and restart persistence. Tests must preserve Python 3.10/3.12/3.14 support, exact 100% owned production statement/branch coverage and public docstrings, package/container gates, security/SAST checks, and the then-current exact-source/review policy.

Operational acceptance must also prove that policy/readiness evidence contains no provider secret, ciphertext, key material, or credential-bearing DSN. An ACTIVE-PR implementation is not a protected-main guarantee.

## Rollback and supersession

A future implementation may choose Fernet/MultiFernet, an external secret-manager-backed store, or another reviewed encryption primitive if it preserves the explicit policy, no-silent-downgrade, migration, rotation, interoperability, and recovery requirements above. This ADR may be superseded only by a decision that names the replacement confidentiality authority and supplies equivalent or stronger fail-closed transition and recovery semantics.

## References

Joint Task Force. (2025). *Security and privacy controls for information systems and organizations* (NIST Special Publication 800-53, Revision 5, Release 5.2.0). National Institute of Standards and Technology. https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final

National Institute of Standards and Technology. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST Special Publication 800-218). https://doi.org/10.6028/NIST.SP.800-218

The cryptography developers. (2026). *Fernet (symmetric encryption)*. https://cryptography.io/en/latest/fernet/
