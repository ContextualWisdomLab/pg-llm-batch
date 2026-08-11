# ADR: PostgreSQL transport encryption and server identity

- **Status:** PLANNED — Issue #123
- **Decision owner:** pg-llm-batch database transport boundary
- **Protected-main baseline:** no package-owned `sslmode` policy; `resolve_dsn()` returns the selected non-empty DSN to Psycopg/libpq
- **Implementation dependency:** integrate or supersede #87, #89, and the overlapping #53 database/transaction stack before source implementation

## Context

`pg-llm-batch` stores and processes prompts, provider configuration and secret-store data, queue/batch/request state, and durable provider lifecycle evidence in PostgreSQL. Protected main validates only that a bootstrap DSN exists before handing connection authority to Psycopg/libpq; repository source does not currently define an explicit PostgreSQL transport-encryption or server-identity policy.

PostgreSQL 18 documents libpq's default `sslmode` as `prefer`. That mode may use plaintext when TLS is unavailable and does not authenticate the server. PostgreSQL explicitly characterizes the default as a backward-compatibility choice that is not recommended for secure deployments. `verify-full` provides encryption, CA validation, and hostname verification; `verify-ca` provides encryption and CA validation with a different server-name assurance boundary. PostgreSQL also documents `channel_binding=require` as an additional mitigation against server spoofing for SCRAM authentication.

A single unconditional `verify-full` rewrite is not appropriate for every package use: local Unix sockets and deliberately isolated loopback development have different transport properties, and embedding hosts may own libpq service files, private PKI, or other connection policy. Conversely, silently accepting the libpq default for a remote TCP database is not a defensible commercial security default when the deployment expects authenticated encrypted transport.

## Decision

Issue #123 shall introduce an **explicit deployment-selectable PostgreSQL transport policy** rather than infer security posture from environment names or mutate caller connection strings opportunistically.

1. **Local-development compatibility.** A deliberately selected local Unix-socket or explicit loopback development mode may retain a less restrictive transport requirement when the operator owns that risk. The policy must be explicit; localhost must not silently become a proxy for every production trust decision.
2. **Secure remote mode.** When the deployment selects secure remote PostgreSQL transport, package-owned connection construction must reject downgrade-capable or unauthenticated settings such as missing policy, `sslmode=disable`, `allow`, or `prefer` before package-owned network/authentication work. `sslmode=verify-full` is the preferred security-sensitive target. `verify-ca` may be an explicit alternative only when the deployment's private-CA policy makes hostname verification intentionally unnecessary and that residual risk is documented.
3. **No ad-hoc DSN rewriting.** Connection information must be parsed/validated through Psycopg/libpq-compatible conninfo facilities. URI and keyword conninfo forms, service-file authority, and #89's exact explicit-versus-ambient source semantics must remain unambiguous.
4. **Trust material remains deployment-owned.** CA certificates, client certificates/keys, service files, and related private material are deployment inputs. They must not be embedded in repository source or copied into argv, logs, telemetry, generated evidence, or bounded error messages.
5. **Server-spoofing defense is explicit.** Certificate validation is the primary TLS server-identity control. Where SCRAM is used and the deployment selects the stronger requirement, `channel_binding=require` may be composed as an additional mitigation; it is not documented as a substitute for the chosen TLS/server-identity policy.
6. **Confidential diagnostics.** Package-owned validation errors identify only fixed policy/field categories. DSNs, passwords, certificate contents, provider credentials, prompts/results, SQL text, bind values, and arbitrary libpq error strings must not become exported diagnostic authority.
7. **Host-owned connection authority remains supported.** Embedding hosts that intentionally own libpq service-file or injected connection policy remain supported through an explicit host-owned mode. That mode is not equivalent to a package proof that transport is secure; the host must provide deployment evidence.

## Alternatives considered

### Keep libpq defaults

Rejected for secure remote deployments. The default `prefer` mode is opportunistic and lacks server authentication; absence of an explicit policy can therefore become an accidental downgrade path.

### Force `sslmode=verify-full` into every DSN

Rejected. Blind string rewriting can break conninfo quoting, service-file semantics, local Unix-socket workflows, private deployment policy, and #89's exact source-authority contract. It also conflates transport policy with caller data mutation.

### Require only `sslmode=require`

Rejected as the acquisition-grade default because it encrypts traffic without independently proving that the endpoint is the intended PostgreSQL server. It can remain a separately reviewed compatibility choice only if the threat model and deployment network provide equivalent identity assurance, which the package must not assume.

### Delegate everything to the host

Rejected as the only package posture. pg-llm-batch owns direct PostgreSQL connection construction in standalone and package-provided paths, so it must provide a fail-closed secure mode and make residual host ownership explicit.

## Test and acceptance contract

Implementation is not accepted until realistic tests prove at least:

- the protected-main failure mode as RED: a remote TCP DSN without explicit reviewed transport policy reaches ordinary connection construction;
- a trusted CA plus matching hostname succeeds under secure remote mode;
- wrong CA, hostname mismatch, plaintext/downgrade configuration, and disallowed `sslmode` values fail closed before useful application work;
- the deliberate local Unix-socket/loopback development exception behaves exactly as documented;
- service-file or embedding-host-owned connection authority is not silently rewritten;
- diagnostics do not contain DSNs, passwords, certificate material, prompt/result content, SQL text, bind values, or arbitrary provider/libpq payloads;
- restart/recovery does not mutate durable product data merely because the transport policy rejects a connection;
- composition with #117 does not reintroduce credential-bearing DSNs in process argv;
- composition with #122 retains finite connection/statement/lock budgets without converting a TLS failure into an unbounded wait;
- Python 3.10, 3.12, and 3.14 pass; owned production statement/branch coverage and public docstrings remain 100%; and applicable package/container/security/SAST/exact-source/release gates pass on the final integrated head.

## Rollback and recovery

A rollout must distinguish policy rollback from data rollback. Transport-policy rejection occurs before package-owned database work and must not require modifying persisted batch state. If a deployment cannot satisfy the selected secure mode, operators may restore the last reviewed policy only through an explicit configuration rollback; they must not silently fall back from authenticated TLS to opportunistic or plaintext transport. Certificate rotation/recovery remains deployment-owned and must be exercised before release where the package relies on that deployment evidence.

## Interactions

- **#87:** deterministic database/store connection ownership; compose after protected integration rather than racing its connection surfaces.
- **#89:** exact DSN source/type precedence; transport validation must preserve this authority.
- **#53 stack:** durable lifecycle/checkpoint transaction helpers; transport policy must cover package-owned connection paths consistently without changing tenant/RLS semantics.
- **#117:** controls credential-bearing DSN exposure through the CLI; distinct from network encryption/server identity.
- **#122:** controls finite PostgreSQL connection/statement/lock waits; distinct from transport authenticity/confidentiality.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: SSL support*. https://www.postgresql.org/docs/18/libpq-ssl.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Preventing server spoofing*. https://www.postgresql.org/docs/18/preventing-server-spoofing.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Database connection control functions*. https://www.postgresql.org/docs/18/libpq-connect.html

The Psycopg Team. (2026). *Psycopg 3 documentation: conninfo — manipulate connection strings*. https://www.psycopg.org/psycopg3/docs/api/conninfo.html
