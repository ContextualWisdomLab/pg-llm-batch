# ADR 0023: Authenticate remote PostgreSQL server identity in the pg8000 production adapter

- Status: Proposed
- Date: 2026-09-11
- Owners: PostgreSQL infrastructure boundary / issue #123
- Decision branch: Draft #342

## Problem

The production-driver migration in Draft #323 selects pg8000 1.31.5 behind `PostgresDriverPort`. The inherited `Pg8000CandidateDriverAdapter.connect()` passes the validated host, port, database, user, optional password, and optional connect timeout to pg8000, but supplies no `ssl_context`.

pg8000 documents `ssl_context=None` as attempting SSL and then falling back to an ordinary socket when the server refuses SSL. That is incompatible with the package-created remote PostgreSQL connection boundary: a remote PostgreSQL selector must not silently lose transport encryption, and encryption without certificate and hostname verification is not server authentication.

The same package is used for local development and embedding. Existing local PostgreSQL runtime smokes use explicit loopback targets that are not provisioned with a trusted TLS identity. Host applications may also inject another `PostgresDriverPort` when they intentionally own connection construction. The package therefore needs a narrow default policy with an explicit distinction between host trust-store authority and package connection configuration.

Python's TLS defaults create a second security consideration. `ssl.create_default_context()` enables TLS key logging when process environment variable `SSLKEYLOGFILE` is set. Default CA loading also follows the host OpenSSL/platform trust configuration; on OpenSSL-backed platforms, the default verify paths expose the process-level CA environment keys conventionally named `SSL_CERT_FILE` and `SSL_CERT_DIR`. A package-created database connection must not silently export TLS session keys, while host-level CA trust remains a deployment/platform concern rather than a DSN or package-secret concern.

## Constraints

- Preserve the provider-neutral `PostgresDriverPort` and its current selector, timeout, transaction, thread-affinity, JSONB, SQLSTATE, and service-file semantics.
- Preserve exact pg8000 1.31.5 distribution and import-origin admission in `pg8000_driver_adapter`.
- Do not add ambient `PG*`, `.env`, arbitrary DSN TLS flags, certificate paths, or per-connection trust-material discovery as a second package configuration authority.
- Admit the Python/OpenSSL/platform default CA store as host trust authority. On platforms where OpenSSL default verify paths honor process-level CA location variables, those variables are part of the host trust-store boundary, not package selector grammar.
- Do not honor `SSLKEYLOGFILE` as package-created PostgreSQL TLS key-export authority.
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

### Parse caller-supplied TLS flags or trust material through DSN/package environment configuration

Rejected for this slice. That would expand the connection grammar and create new trust-material precedence, secrecy, validation, and configuration-governance contracts. A future caller-owned trust-policy object may be added through a separately reviewed port if a deployment needs per-connection or per-tenant trust selection.

This rejection does not redefine the operating system/Python/OpenSSL CA store as package configuration. The default CA loader may consume host-managed trust locations, including OpenSSL default-path environment variables where the platform supports them. That authority is process/deployment scoped and is deliberately covered by the real TLS acceptance harness.

### Use `ssl.create_default_context()` unchanged

Rejected after review. Its peer-verification defaults are suitable, but Python documents that it enables TLS key logging when `SSLKEYLOGFILE` is present. Package-created PostgreSQL sessions must not acquire an ambient session-key export sink merely because another process-level debugging setting exists.

### Construct a strict client context, load host default CAs, and never auto-enable key logging

Selected. The adapter constructs `SSLContext(PROTOCOL_TLS_CLIENT)`, explicitly enables `VERIFY_X509_PARTIAL_CHAIN | VERIFY_X509_STRICT`, calls `load_default_certs()`, and validates `check_hostname=True`, `verify_mode=CERT_REQUIRED`, and `keylog_filename is None` before raw pg8000 access. This retains the platform trust store and hostname authentication while preventing `SSLKEYLOGFILE` from enabling key export through this package path. Explicit loopback targets keep the existing local-development behavior.

## Decision

`Pg8000DriverAdapter`, the production implementation selected by `retained_postgres_driver()`, wraps only the already-admitted pg8000 DB-API connection factory.

For a validated non-loopback host it:

1. creates a fresh `SSLContext(PROTOCOL_TLS_CLIENT)`;
2. explicitly enables `VERIFY_X509_PARTIAL_CHAIN` and `VERIFY_X509_STRICT`;
3. loads the platform/Python/OpenSSL default CA trust through `load_default_certs()`;
4. verifies `check_hostname is True`, `verify_mode == ssl.CERT_REQUIRED`, and `keylog_filename is None`;
5. supplies that exact context as pg8000's `ssl_context` argument; and
6. fails before raw driver access with `PostgreSQL TLS policy is unavailable` if the trust context cannot be constructed or any of those invariants is weakened.

For exact loopback identities (`localhost`, IPv4 loopback, IPv6 loopback), it does not inject `ssl_context`; this preserves the current bounded development exception. Private RFC1918/ULA addresses, Kubernetes/service DNS names, and other non-loopback hosts are remote for this policy and receive verified TLS.

The lower-level candidate adapter remains policy-neutral so its parser/adapter behavior is not duplicated or forked. Host software that deliberately owns a different TLS connection policy continues to inject a `PostgresDriverPort`; it does not mutate this package's DSN grammar.

The host CA store is an explicit deployment authority. On OpenSSL-backed platforms, Python's default verify paths may honor `SSL_CERT_FILE` and `SSL_CERT_DIR`; the package does not parse those values, copy trust material, or expose them through its selectors. `SSLKEYLOGFILE` is different: it controls export of TLS session keys rather than trust anchors, so package-created PostgreSQL contexts deliberately do not inherit it.

The existing permanent pg8000 candidate PostgreSQL smoke is also the realistic acceptance owner for this boundary. It uses the disposable repository PostgreSQL container's non-loopback bridge address, provisions an ephemeral CI-only CA and server identity, and executes the production `Pg8000DriverAdapter` rather than a TLS mock. The acceptance harness binds the ephemeral CA through the same host trust-store path used by `load_default_certs()`. The matrix requires:

- trusted CA plus matching IP subject alternative name to establish TLS, confirmed from `pg_catalog.pg_stat_ssl`;
- an unrelated CA to fail verification;
- a CA-trusted certificate with a mismatching IP subject alternative name to fail peer-identity verification;
- the same remote selector to fail when PostgreSQL TLS is disabled, proving no plaintext downgrade;
- ambient `SSLKEYLOGFILE` not to become a key-log sink for the constructed production context; and
- TLS failure rendering used by the acceptance harness not to contain the ephemeral database password.

The test PKI itself must remain RFC 5280-conforming. The ephemeral CA asserts critical `basicConstraints = CA:TRUE` and critical `keyUsage = keyCertSign,cRLSign`; leaf certificates assert critical `CA:FALSE`, TLS server key usage, `extendedKeyUsage = serverAuth`, subject/authority key identifiers, and the tested IP SAN. The harness does not disable `VERIFY_X509_STRICT` to make malformed test certificates pass.

## Evidence

The test-first head `eee15706ffe214cd744667740fab75303a9835f8` added only the remote-TLS regression. Hosted CI run `34561345681` reached the non-integration suite and produced the expected RED: three remote-host cases failed because pg8000 kwargs contained no `ssl_context`; 1681 tests passed, 3 failed, and 5 were deselected. The later workflow cancellation caused by descendant commits does not change that already-terminal failing job evidence.

Minimum production repair `77089494bed2ee4b81cda0d7bc46446f6cc81fc8` added the first production TLS policy without changing the abstract port. Exact candidate `7f6864cd4fb94ef9a0e76955b06babad990c8c00` additionally covered trust-context construction failure and rejected contexts with either hostname verification or `CERT_REQUIRED` disabled.

The first realistic TLS acceptance head `dc6b1cc66065117fbd6a93acce8dcb0b94afcc56` then produced a useful compatibility RED in CI `34564646091`. Python 3.10 and 3.12 completed the real pg8000/PostgreSQL smoke, while Python 3.14 rejected the harness-generated CA during the matching-identity success case with `CERTIFICATE_VERIFY_FAILED` because the CA certificate did not contain a key-usage extension. This was a test-PKI defect, not a reason to weaken production verification. Python 3.13+ enables `VERIFY_X509_STRICT` in `create_default_context()` by default, and RFC 5280 defines the CA/basic-constraints and certificate-signing key-usage relationship. Descendant `92e5b8ec4246329080f34bc772dbd60102d3df11` repaired only the generated CI certificates with explicit CA/leaf constraints and key usages; it did not disable strict verification.

Review of exact `c61a91a36e76cd9b9127e1d9eb98aff776bfdf48` found a second policy-authority defect. Python 3.14 documents that `create_default_context()` honors `SSLKEYLOGFILE`, while the branch claimed that no ambient TLS environment authority existed. The existing real smoke also intentionally used the OpenSSL CA environment path, showing that CA trust and key export had been conflated in the ADR. Test-first `506fc36499ac191d6ea328e0bdf20e2df1e65d95` adds the regression that package-created remote TLS must not inherit ambient key logging. Descendants replace `create_default_context()` with an explicit client context, retain strict X.509 and host default CA loading, and reject any constructed context with key logging enabled.

Earlier ADR-bearing validation also exposed repository contracts rather than TLS-policy defects: the ADR heading must use canonical `# ADR NNNN:` form, and every owned production nested callable must carry a docstring to preserve 100% docstring coverage. Those findings were repaired on ordinary descendants without weakening either gate.

## Consequences and follow-up

Remote package-created pg8000 connections can no longer rely on pg8000's plaintext fallback once this branch is normally integrated. The trust anchor is the Python/platform/OpenSSL default CA store, hostname verification uses the validated host supplied to pg8000, strict X.509 validation is enabled consistently across supported Python versions, and process-level `SSLKEYLOGFILE` does not enable PostgreSQL TLS session-key export through this adapter.

Enterprise private CAs can participate through the deployment's default trust-store authority where the platform supports it. A future explicit caller-owned trust-policy capability is still appropriate when trust selection must vary per connection, tenant, or application boundary. That design must define authority, public certificate custody, precedence, cache/lifetime behavior, diagnostics, and interaction with service-file parsing rather than silently expanding DSN grammar.

The branch contains realistic TLS-enabled PostgreSQL acceptance for the core issue #123 transport matrix. Issue closure still requires this exact capability to survive current-head CI, independent review/thread resolution, normal protected-stack integration, post-integration acceptance, and immutable release evidence. The acceptance does not prove certificate rotation/revocation operations or caller-specific trust-policy semantics.

## References

Cooper, D., Santesson, S., Farrell, S., Boeyen, S., Housley, R., & Polk, W. (2008). *Internet X.509 public key infrastructure certificate and certificate revocation list (CRL) profile* (RFC 5280). RFC Editor. https://www.rfc-editor.org/rfc/rfc5280

pg8000 project. (n.d.). *pg8000 1.31.5 documentation*. PyPI. https://pypi.org/project/pg8000/1.31.5/

PostgreSQL Global Development Group. (n.d.). *SSL support*. PostgreSQL 17 documentation. https://www.postgresql.org/docs/17/libpq-ssl.html

PostgreSQL Global Development Group. (n.d.). *Database connection control functions*. PostgreSQL 17 documentation. https://www.postgresql.org/docs/17/libpq-connect.html

Python Software Foundation. (2026). *ssl — TLS/SSL wrapper for socket objects*. Python 3.14 documentation. https://docs.python.org/3.14/library/ssl.html
