# ADR-0023: Authenticate remote PostgreSQL server identity in the pg8000 production adapter

- Status: Proposed
- Date: 2026-09-11
- Owners: PostgreSQL infrastructure boundary / issue #123
- Decision branch: Draft #342

## Problem

The production-driver migration in Draft #323 selects pg8000 1.31.5 behind `PostgresDriverPort`. The inherited `Pg8000CandidateDriverAdapter.connect()` passes the validated host, port, database, user, optional password, and optional connect timeout to pg8000, but supplies no `ssl_context`.

pg8000 documents `ssl_context=None` as attempting SSL and then falling back to an ordinary socket when the server refuses SSL. That is incompatible with the package-created remote connection boundary: a remote PostgreSQL selector must not silently lose transport encryption, and encryption without certificate and hostname verification is not server authentication.

The same package is used for local development and embedding. Existing local PostgreSQL runtime smokes use explicit loopback targets that are not provisioned with a trusted TLS identity. Host applications may also inject another `PostgresDriverPort` when they intentionally own connection construction. The package therefore needs a narrow default policy without acquiring ambient trust-store, environment-variable, `.env`, or caller-secret authority.

## Constraints

- Preserve the provider-neutral `PostgresDriverPort` and its current selector, timeout, transaction, thread-affinity, JSONB, SQLSTATE, and service-file semantics.
- Preserve exact pg8000 1.31.5 distribution and import-origin admission in `pg8000_driver_adapter`.
- Do not add ambient `PG*`, TLS, `.env`, or arbitrary DSN option discovery as a second policy authority.
- Keep the package's explicit injected-driver seam for embedding hosts that own a different connection policy.
- Keep diagnostics content-free: TLS-policy construction failure must not expose certificate-store paths, hosts, DSNs, usernames, passwords, or platform details.
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

## Evidence

The test-first head `eee15706ffe214cd744667740fab75303a9835f8` added only the remote-TLS regression. Hosted CI run `34561345681` reached the non-integration suite and produced the expected RED: three remote-host cases failed because pg8000 kwargs contained no `ssl_context`; 1681 tests passed, 3 failed, and 5 were deselected. The later workflow cancellation caused by descendant commits does not change that already-terminal failing job evidence.

Minimum production repair `77089494bed2ee4b81cda0d7bc46446f6cc81fc8` adds the production TLS policy without changing the abstract port. Exact candidate `7f6864cd4fb94ef9a0e76955b06babad990c8c00` additionally covers trust-context construction failure and rejects contexts with either hostname verification or `CERT_REQUIRED` disabled.

At the time this ADR was proposed, Release Acceptance `34561425250` on exact `7f6864cd...` was terminal success and CI `34561425189` was still queued. Those workflow states are evidence snapshots, not release authority.

## Consequences and follow-up

Remote package-created pg8000 connections can no longer rely on pg8000's plaintext fallback once this branch is normally integrated. The default trust anchor becomes the Python/platform default CA store, and hostname verification uses the validated host supplied to pg8000.

Enterprise deployments using a private CA may need an explicit caller-owned trust-policy capability later. That design must define authority, secret/public certificate custody, precedence, cache/lifetime behavior, diagnostics, and interaction with service-file parsing instead of silently adding environment-based discovery.

Issue #123 remains open until realistic TLS-enabled PostgreSQL acceptance proves: trusted CA + matching identity success; wrong/untrusted CA failure; hostname mismatch failure; refusal of plaintext downgrade when TLS cannot be negotiated; preservation of caller-owned/injected-driver policy; confinement of the loopback exception; and content-safe TLS/authentication diagnostics. Protected integration and immutable release evidence remain separate gates.

## References

pg8000 project. (n.d.). *pg8000 1.31.5 documentation*. PyPI. https://pypi.org/project/pg8000/1.31.5/

PostgreSQL Global Development Group. (n.d.). *SSL support*. PostgreSQL 17 documentation. https://www.postgresql.org/docs/17/libpq-ssl.html

PostgreSQL Global Development Group. (n.d.). *Database connection control functions*. PostgreSQL 17 documentation. https://www.postgresql.org/docs/17/libpq-connect.html

Python Software Foundation. (n.d.). *ssl — TLS/SSL wrapper for socket objects*. Python 3.14 documentation. https://docs.python.org/3.14/library/ssl.html
