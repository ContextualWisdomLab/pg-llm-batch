# Runtime store provisioning boundary

## Operator action

Provision or migrate `com_config` and `com_secrets` with the explicit package schema before starting an ordinary application process:

```bash
python -m pg_llm_batch init-db
```

After provisioning, the normal application role needs schema `USAGE` plus only the table privileges required by its configured read/write operations. It does not need schema `CREATE` merely to construct `PostgresConfigStore` or `SecretStore`. Production application roles must be `NOSUPERUSER NOBYPASSRLS` so administrative privilege cannot silently bypass row-security boundaries owned elsewhere in the package schema.

Runtime constructors issue bounded read-only `pg_catalog` capability probes. The search-path-resolved relation must be an ordinary base table, every required column must have the expected PostgreSQL data type, and the current role must have schema `USAGE` plus table `SELECT`. The configured storage key (`config_key` or `secret_key`) must also be backed by a valid, ready, non-partial, non-expression unique index with exactly one key column so the runtime `ON CONFLICT (key)` write contract has a compatible arbiter before application writes begin. If that index backs a PostgreSQL constraint, the constraint must be `NOT DEFERRABLE`; PostgreSQL does not permit a `DEFERRABLE` constraint to act as an `ON CONFLICT` arbiter. A storage key that appears only as an `INCLUDE` payload column does not satisfy this boundary because PostgreSQL explicitly excludes included columns from uniqueness enforcement. Missing tables, missing columns, selectable views, type mismatches, insufficient read privileges, missing or deferrable unique-key authority, or other incompatible relations fail closed with fixed package diagnostics; database exception text, DSNs, SQL values, and credentials are not retained in exported exception context. Connections acquired before a failed probe are closed deterministically.

Built-in configuration rows are seeded only at the explicit schema boundary with `ON CONFLICT (config_key) DO NOTHING`. Existing operator values therefore survive provisioning replay and upgrades. The packaged schema and deployable PostgreSQL initialization schema remain byte-identical.

## Secret encryption policy

`SecretStore` requires Fernet encryption for every runtime construction and every newly persisted secret. A missing Fernet key, malformed key, unavailable cryptography dependency, or explicit `require_encryption=False` request fails with a fixed `ConfigError` before PostgreSQL connection acquisition. The historical `require_encryption` keyword is retained only so existing callers that explicitly pass `True` do not break at the call boundary; it is not a policy switch and cannot re-enable reversible Base64 persistence.

Runtime secret writes produce Fernet ciphertext only. Runtime reads reject any durable row whose encryption flag is not the exact boolean `TRUE`; the runtime no longer Base64-decodes historical unencrypted values. Startup also positively proves that `com_secrets` contains no `is_encrypted IS NOT TRUE` row before accepting the store. A deployment with historical unencrypted rows must therefore inventory and migrate them through a separately reviewed, atomic, recoverable migration before starting the hardened runtime. Do not convert those rows in-place without a verified backup, rollback procedure, key-custody plan, and post-migration proof that no unencrypted rows remain.

This boundary is intentionally narrower than the complete secret lifecycle tracked separately. It does not itself perform the historical-row migration, rotate keys, retire decrypt-only keys, prove key custody, define retention, or convert successful encryption into a SOC 2, CSAP, or NIST certification claim.

## Security rationale

PostgreSQL grants object creation through a schema's `CREATE` privilege; ordinary access requires separate schema `USAGE` and object privileges. Removing implicit runtime DDL permits a least-privilege application role. The runtime probe validates the relation resolved through the active `search_path`; it does not establish that relation's schema ownership. Operators must therefore use a trusted search path and prevent untrusted roles from creating objects in schemas searched ahead of the provisioned package relation. PostgreSQL also states that `CREATE TABLE IF NOT EXISTS` does not prove that an existing relation has the expected structure, so an implicit create statement is not a schema-compatibility check. Runtime compatibility therefore derives from bounded read-only catalog and privilege metadata for the resolved relation rather than from successful execution against an arbitrary selectable relation.

PostgreSQL implements uniqueness through unique indexes and resolves `INSERT ... ON CONFLICT` using unique-index inference. `pg_index.indisunique`, `indisvalid`, and `indisready` distinguish indexes that are unique, valid, and ready for inserts; `indnkeyatts` distinguishes key columns from included attributes, while `indpred` and `indexprs` identify partial and expression indexes. PostgreSQL's `CREATE INDEX` contract further specifies that `INCLUDE` columns are non-key payload and are disregarded for uniqueness or exclusion constraints. PostgreSQL also limits `ON CONFLICT` arbiters to non-deferrable uniqueness authority: when a qualifying index backs a constraint, the probe correlates `pg_constraint.conindid` with the index and rejects `condeferrable = true`. The runtime compatibility probe therefore inspects only the first `indnkeyatts` entries of `indkey` when matching the storage key and rejects both a readable lookalike table whose storage key is merely included behind some other unique key and one whose only matching uniqueness is deferrable. Neither shape can satisfy the package's simple-column `ON CONFLICT (config_key)` or `ON CONFLICT (secret_key)` write contract.

Fernet provides authenticated symmetric encryption for stored secret values when a valid key is configured, but the cryptographic primitive does not by itself define deployment authorization, key custody, rotation, recovery, retention, or audit policy. Mandatory runtime encryption removes the previous insecure compatibility path instead of treating reversible obfuscation as an acceptable environment-specific fallback.

## Rollback and recovery

Rollback of unrelated runtime-store provisioning changes must preserve the deployment's Fernet key and mandatory encryption posture. Older package versions that permit Base64 fallback reopen the at-rest confidentiality defect and are not a security-equivalent rollback target. Before any rollback across this security boundary, verify the target version's secret-store behavior, retain encrypted database backups and key-recovery material under the deployment's custody controls, and prove that rollback will not create or decode unencrypted secret rows.

A failed runtime schema probe is repaired by applying the reviewed schema with a provisioning identity and retrying with the ordinary runtime identity. A failed encryption-readiness probe is repaired by the separately reviewed historical-row migration, not by disabling encryption. Do not grant broad schema `CREATE`, `SUPERUSER`, or `BYPASSRLS`, add an untrusted writable schema ahead of the provisioned relation in `search_path`, or weaken secret encryption merely to silence readiness.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: CREATE INDEX*. https://www.postgresql.org/docs/18/sql-createindex.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: CREATE TABLE*. https://www.postgresql.org/docs/18/sql-createtable.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: INSERT*. https://www.postgresql.org/docs/18/sql-insert.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: pg_constraint*. https://www.postgresql.org/docs/18/catalog-pg-constraint.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: pg_index*. https://www.postgresql.org/docs/18/catalog-pg-index.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Privileges*. https://www.postgresql.org/docs/18/ddl-priv.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Schemas*. https://www.postgresql.org/docs/18/ddl-schemas.html

The Psycopg Team. (2026). *Psycopg 3 documentation: Basic module usage*. https://www.psycopg.org/psycopg3/docs/basic/usage.html

The cryptography developers. (2026). *Fernet (symmetric encryption)*. https://cryptography.io/en/latest/fernet/

Joint Task Force. (2025). *Security and privacy controls for information systems and organizations* (NIST Special Publication 800-53, Revision 5, Release 5.2.0). National Institute of Standards and Technology. https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final
