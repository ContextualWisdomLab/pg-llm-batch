# Runtime store provisioning boundary

## Operator action

Provision or migrate `com_config` and `com_secrets` with the explicit package schema before starting an ordinary application process:

```bash
python -m pg_llm_batch init-db
```

After provisioning, the normal application role needs schema `USAGE` plus only the table privileges required by its configured read/write operations. It does not need schema `CREATE` merely to construct `PostgresConfigStore` or `SecretStore`.

Runtime constructors issue bounded read-only capability probes for required columns. Missing tables, missing columns, permission failures, or incompatible relations fail closed with fixed package diagnostics; database exception text, DSNs, SQL values, and credentials are not retained in exported exception context. Connections acquired before a failed probe are closed deterministically.

Built-in configuration rows are seeded only at the explicit schema boundary with `ON CONFLICT (config_key) DO NOTHING`. Existing operator values therefore survive provisioning replay and upgrades. The packaged schema and deployable PostgreSQL initialization schema remain byte-identical.

## Security rationale

PostgreSQL grants object creation through a schema's `CREATE` privilege; ordinary access requires separate schema `USAGE` and object privileges. Removing implicit runtime DDL permits a least-privilege application role and avoids trusting every role able to create objects in the active `search_path`. PostgreSQL also states that `CREATE TABLE IF NOT EXISTS` does not prove that an existing relation has the expected structure, so an implicit create statement is not a schema-compatibility check.

## Rollback and recovery

Rollback restores the previous package version and its constructor-owned bootstrap behavior; it does not delete provisioned tables or operator values. A failed runtime probe is repaired by applying the reviewed schema with a provisioning identity and retrying with the ordinary runtime identity. Do not grant broad schema `CREATE` merely to silence a readiness failure.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: CREATE TABLE*. https://www.postgresql.org/docs/18/sql-createtable.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Privileges*. https://www.postgresql.org/docs/18/ddl-priv.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Schemas*. https://www.postgresql.org/docs/18/ddl-schemas.html

The Psycopg Team. (2026). *Psycopg 3 documentation: Basic module usage*. https://www.psycopg.org/psycopg3/docs/basic/usage.html
