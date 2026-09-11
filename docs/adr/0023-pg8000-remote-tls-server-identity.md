# ADR 0023: Authenticate remote PostgreSQL server identity in the pg8000 production adapter

- Status: Proposed
- Date: 2026-09-11
- Owners: PostgreSQL infrastructure boundary / issue #123
- Decision branch: Draft #342

## Problem

The production-driver migration in Draft #323 selects pg8000 1.31.5 behind `PostgresDriverPort`. The inherited `Pg8000CandidateDriverAdapter.connect()` passes the validated host, port, database, user, optional password, and optional connect timeout to pg8000, but supplies no `ssl_context`.

pg8000 documents `ssl_context=None` as attempting SSL and then falling back to an ordinary socket when the server refuses SSL. That is incompatible with the package-created remote PostgreSQL connection boundary: a remote PostgreSQL selector must not silently lose transport encryption, and encryption without certificate and hostname verification is not server authentication.

The same package is used for local development and embedding. Existing local PostgreSQL runtime smokes use explicit loopback targets that are not provisioned with a trusted TLS identity. Host applications may also inject another `PostgresDriverPort` when they intentionally own connection construction. The package therefore needs a narrow default policy without acquiring ambient trust-store, environment-variable, `.env`, or caller-secret authority.

## Constraints

- Preserve the provider-neutral `PostgresDriverPort` and its current selector, timeout, transaction, thread-affinity, JSONB, SQLSTATE, and service-file semantics.
- Preserve exact pg8000 1.31.5 distribution and import-origin admission in `pg8000_driver_adapter`.
- Do not add ambient `PG*`, TLS, `.env`, or arbitrary DSN option discovery as a second policy authority.
- Keep the package's explicit injected-driver seam for embedding hosts that own a different connection policy.
- Keep diagnostics content-free: TLS-policy construction and handshake failures must not expose certificate-store paths, hosts, DSNs, usernames, passwords, or platform details through package-authored diagnostics or acceptance output.
- Keep the deliberate local-development exception explicit and mechanically bounded to `localhost`, IPv4 loopback (`127.0.0.0/8`), and IPv6 loopback (`::1`).
- Do not treat a unit-level SSL-context contract as proof of real certificate or PostgreSQL TLS behavior.

## Alternatives considered

### Keep pg8000's default `ssl_context=None`

Rejected. pg8000 may fall back to plaintext if the remote server refuses SSL. This fails the remote fail-closed requirement and provides no package-level server-identity guarantee.

### Pass `ssl_context=True`

Rejected. pg8000 documents this as an SSL context with minimum checks. It requires SSL but does not establish the explicit certificate and hostname-verification contract required by issue #123.

### Require verified TLS for every connection, including loopback

Deferred. This is the preferred long-term deployment posture, but the current local PostgreSQL development/runtime-smoke path has no reviewed certificate provisioning contract. Making that unrelated infrastructure migration part of this repair would broaden the bounded change and would obscure the remote downgrade defect. Loopback is therefore a temporary explicit exception, not a general private-network exception.

### Accept caller-supplied TLS flags or trust material through DSN/environment variables

Rejected for this slice. That would expand the connection grammar and create new trust-material precedence, secrecy, validation, and configuration-governance contracts. A future caller-owned trust-policy object may be added through a separately reviewed port if enterprise private-CA deployments require it.

### Apply a verified system-trust `SSLContext` only to non-loopback targets

Selected. `ssl.create_default_context()` establishes certificate verification and hostname checking using the platform trust store. The production adapter validates that the resulting context still has `check_hostname=True` and `verify_mode=CERT_REQUIRED` before passing it to pg8000. Explicit loopback targets keep the existing local-development behavior, while every other admitted TCP host fails closed if the verified context cannot be constructed.

## Decision

`Pg8000DriverAdapter`, the production implementation selected by `retained_postgres_driver()`, wraps only the already-admitted pg8000 DB-API connection factory.

For a validated non-loopback host it:

1. constructs a fresh context with `ssl.create_default_context()`;
2. verifies `check_hostname is True` and `verify_mode == ssl.CERT_REQUIRED`;
3. supplies that exact context as pg8000's `ssl_context` argument; and
4. fails before raw driver access with `PostgreSQL TLS policy is unavailable` if the trust context cannot be constructed or is weakened.

For exact loopback identities (`localhost`, IPv4 loopback, IPv6 loopback), it does not inject `ssl_context`; this preserves the current bounded development exception. Private RFC1918/ULA addresses, Kubernetes/service DNS names, and other non-loopback hosts are remote for this policy and receive verified TLS.

The lower-level candidate adapter remains policy-neutral so its parser/adapter behavior is not duplicated or forked. Host software that deliberately owns a different TLS connection policy continues to inject a `PostgresDriverPort`; it does not mutate this package default through ambient configuration.

The existing permanent pg8000 candidate PostgreSQL smoke is also the realistic acceptance owner for this boundary. It uses the disposable repository PostgreSQL container's non-loopback bridge address, provisions an ephemeral CI-only CA and server identity, and executes the production `Pg8000DriverAdapter` rather than a TLS mock. The same matrix requires:

- trusted CA plus matching IP subject alternative name to establish TLS, confirmed from `pg_catalog.pg_stat_ssl`;
- an unrelated CA to fail verification;
- a CA-trusted certificate with a mismatching IP subject alternative name to fail peer-identity verification;
- the same remote selector to fail when PostgreSQL TLS is disabled, proving no plaintext downgrade; and
- TLS failure rendering used by the acceptance harness not to contain the ephemeral database password.

The test PKI itself must remain RFC 5280-conforming. The ephemeral CA asserts critical `basicConstraints = CA:TRUE` and critical `keyUsage = keyCertSign,cRLSign`; leaf certificates assert critical `CA:FALSE`, TLS server key usage, `extendedKeyUsage = serverAuth`, subject/authority key identifiers, and the tested IP SAN. The harness does not disable `VERIFY_X509_STRICT` to make malformed test certificates pass.

## Evidence

The test-first head `eee15706ffe214cd744667740fab75303a9835f8` added only the remote-TLS regression. Hosted CI run `34561345681` reached the non-integration suite and produced the expected RED: three remote-host cases failed because pg8000 kwargs contained no `ssl_context`; 1681 tests passed, 3 failed, and 5 were deselected. The later workflow cancellation caused by descendant commits does not change that already-terminal failing job evidence.

Minimum production repair `77089494bed2ee4b81cda0d7bc46446f6cc81fc8` adds the production TLS policy without changing the abstract port. Exact candidate `7f6864cd4fb94ef9a0e76955b06babad990c8c00` additionally covers trust-context construction failure and rejects contexts with either hostname verification or `CERT_REQUIRED` disabled.

The first realistic TLS acceptance head `dc6b1cc66065117fbd6a93acce8dcb0b94afcc56` then produced a useful compatibility RED in CI `34564646091`. Python 3.10 and 3.12 completed the real pg8000/PostgreSQL smoke, while Python 3.14 rejected the harness-generated CA during the matching-identity success case with `CERTIFICATE_VERIFY_FAILED` because the CA certificate did not contain a key-usage extension. This was a test-PKI defect, not a reason to weaken production verification. Python 3.13+ enables `VERIFY_X509_STRICT` in `create_default_context()` by default, and RFC 5280 defines the CA/basic-constraints and certificate-signing key-usage relationship. Descendant `92e5b8ec4246329080f34bc772dbd60102d3df11` repairs only the generated CI certificates with explicit CA/leaf constraints and key usages; it does not disable strict verification or alter the production TLS policy.

Earlier ADR-bearing validation also exposed repository contracts rather than TLS-policy defects: the ADR heading must use canonical `# ADR NNNN:` form, and every owned production nested callable must carry a docstring to preserve 100% docstring coverage. Those findings were repaired on ordinary descendants without weakening either gate.

## Consequences and follow-up

Remote package-created pg8000 connections can no longer rely on pg8000's plaintext fallback once this branch is normally integrated. The default trust anchor becomes the Python/platform default CA store, and hostname verification uses the validated host supplied to pg8000.

Enterprise deployments using a private CA may need an explicit caller-owned trust-policy capability later. That design must define authority, secret/public certificate custody, precedence, cache/lifetime behavior, diagnostics, and interaction with service-file parsing instead of silently adding environment-based discovery.

The branch now contains realistic TLS-enabled PostgreSQL acceptance for the core issue #123 transport matrix. Issue closure still requires this exact capability to survive current-head CI, independent review/thread resolution, normal protected-stack integration, post-integration acceptance, and immutable release evidence. The acceptance does not prove public-PKI availability for a buyer's private database, certificate rotation/revocation operations, or caller-specific trust-policy semantics.

## References

Cooper, D., Santesson, S., Farrell, S., Boeyen, S., Housley, R., & Polk, W. (2008). *Internet X.509 public key infrastructure certificate and certificate revocation list (CRL) profile* (RFC 5280). RFC Editor. https://www.rfc-editor.org/rfc/rfc5280

pg8000 project. (n.d.). *pg8000 1.31.5 documentation*. PyPI. https://pypi.org/project/pg8000/1.31.5/

PostgreSQL Global Development Group. (n.d.). *SSL support*. PostgreSQL 17 documentation. https://www.postgresql.org/docs/17/libpq-ssl.html

PostgreSQL Global Development Group. (n.d.). *Database connection control functions*. PostgreSQL 17 documentation. https://www.postgresql.org/docs/17/libpq-connect.html

Python Software Foundation. (2026). *ssl — TLS/SSL wrapper for socket objects*. Python 3.14 documentation. https://docs.python.org/3.14/library/ssl.html
