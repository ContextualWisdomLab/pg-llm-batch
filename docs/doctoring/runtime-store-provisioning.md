# Runtime store provisioning boundary

## Operator action

Provision or migrate `com_config` and `com_secrets` with the explicit package schema before starting an ordinary application process:

```bash
python -m pg_llm_batch init-db
```

After provisioning, the normal application role needs schema `USAGE` plus only the table privileges required by its configured read/write operations. It does not need schema `CREATE` merely to construct `PostgresConfigStore` or `SecretStore`. Production application roles must be `NOSUPERUSER NOBYPASSRLS` so administrative privilege cannot silently bypass row-security boundaries owned elsewhere in the package schema.

Runtime constructors issue bounded read-only `pg_catalog` capability probes. The search-path-resolved relation must be an ordinary base table, every required column must have the expected PostgreSQL data type, and the current role must have schema `USAGE` plus table `SELECT`. Missing tables, missing columns, selectable views, type mismatches, insufficient read privileges, or other incompatible relations fail closed with fixed package diagnostics; database exception text, DSNs, SQL values, and credentials are not retained in exported exception context. Connections acquired before a failed probe are closed deterministically.

Built-in configuration rows are seeded only at the explicit schema boundary with `ON CONFLICT (config_key) DO NOTHING`. Existing operator values therefore survive provisioning replay and upgrades. The packaged schema and deployable PostgreSQL initialization schema remain byte-identical.

## Secret encryption policy

`SecretStore` now requires Fernet encryption by default. If the caller does not provide a Fernet key, construction fails with a fixed `ConfigError` before PostgreSQL connection acquisition, so an ordinary production path cannot silently fall back to reversible Base64 storage. A caller may select `require_encryption=False` only as an explicit local/development compatibility mode; that mode is obfuscation, not an at-rest confidentiality control, and must not be represented as production encryption or compliance evidence.

This default-hardening boundary is intentionally narrower than the complete secret lifecycle tracked separately. It does not migrate pre-existing rows with `is_encrypted = FALSE`, rotate keys, retire decrypt-only keys, prove key custody, or convert successful encryption into a SOC 2, CSAP, or NIST certification claim. A deployment moving from historical obfuscation to encryption-required operation must inventory and migrate existing unencrypted rows through a separately reviewed atomic migration before treating the store as wholly encrypted at rest.

## Security rationale

PostgreSQL grants object creation through a schema's `CREATE` privilege; ordinary access requires separate schema `USAGE` and object privileges. Removing implicit runtime DDL permits a least-privilege application role. The runtime probe validates the relation resolved through the active `search_path`; it does not establish that relation's schema ownership. Operators must therefore use a trusted search path and prevent untrusted roles from creating objects in schemas searched ahead of the provisioned package relation. PostgreSQL also states that `CREATE TABLE IF NOT EXISTS` does not prove that an existing relation has the expected structure, so an implicit create statement is not a schema-compatibility check. Runtime compatibility therefore derives from bounded read-only catalog and privilege metadata for the resolved relation rather than from successful execution against an arbitrary selectable relation.

Fernet provides authenticated symmetric encryption for stored secret values when a key is supplied, but the cryptographic primitive does not by itself define deployment authorization, key custody, rotation, recovery, retention, or audit policy. Requiring encryption by default removes the previous silent insecure choice while retaining a deliberate, visibly opt-in local/development compatibility path.

## Rollback and recovery

Rollback restores the previous package version and its constructor-owned bootstrap behavior; it does not delete provisioned tables or operator values. Because an older package version may also restore implicit Base64 fallback, rollback must preserve the deployment's Fernet key and explicit encryption requirement rather than treating the historical default as safe. A failed runtime probe is repaired by applying the reviewed schema with a provisioning identity and retrying with the ordinary runtime identity. Do not grant broad schema `CREATE`, `SUPERUSER`, or `BYPASSRLS`, add an untrusted writable schema ahead of the provisioned relation in `search_path`, or disable secret encryption merely to silence a readiness failure.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: CREATE TABLE*. https://www.postgresql.org/docs/18/sql-createtable.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Privileges*. https://www.postgresql.org/docs/18/ddl-priv.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Schemas*. https://www.postgresql.org/docs/18/ddl-schemas.html

The Psycopg Team. (2026). *Psycopg 3 documentation: Basic module usage*. https://www.psycopg.org/psycopg3/docs/basic/usage.html

The cryptography developers. (2026). *Fernet (symmetric encryption)*. https://cryptography.io/en/latest/fernet/

Joint Task Force. (2025). *Security and privacy controls for information systems and organizations* (NIST Special Publication 800-53, Revision 5, Release 5.2.0). National Institute of Standards and Technology. https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final
