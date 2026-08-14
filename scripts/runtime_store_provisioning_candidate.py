#!/usr/bin/env python3
"""Materialize the bounded runtime-store provisioning candidate for read-only CI."""

from __future__ import annotations

from pathlib import Path


CONFIG_PATH = Path("pg_llm_batch/config.py")
PACKAGE_SCHEMA_PATH = Path("pg_llm_batch/schema.sql")
DOCKER_SCHEMA_PATH = Path("docker/postgres/init/02_schema.sql")

CONFIG_CONNECTION = "        self._conn = psycopg.connect(self.dsn)\n"
CONFIG_LOAD_METHOD = "    def _load_cache(self) -> None:\n"
SECRET_CLASS = "class SecretStore:\n"
SECRET_ENCODE_METHOD = "    def _encode(self, raw: str) -> Tuple[str, bool]:\n"

CONFIG_RUNTIME_BLOCK = '''        self._conn = psycopg.connect(self.dsn)
        try:
            self._conn.autocommit = True
            self.cache: Dict[str, Dict[str, Any]] = {}
            schema_ready = True
            try:
                self._verify_schema()
                self._load_cache()
            except Exception:
                schema_ready = False
            if not schema_ready:
                self.close()
                raise ConfigError(
                    "Configuration schema is unavailable or incompatible"
                ) from None
        except BaseException:
            self.close()
            raise

    def _verify_schema(self) -> None:
        """Verify the provisioned config table without acquiring DDL authority."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT config_key, config_value, config_description, updated_at "
                f"FROM {self.TABLE_NAME} WHERE config_key = %s",
                ("__pg_llm_batch_schema_probe__",),
            )

'''

SECRET_RUNTIME_BLOCK = '''        self._conn = psycopg.connect(self.dsn)
        try:
            self._conn.autocommit = True
            self._fernet = None
            if fernet_key and Fernet is not None:
                self._fernet = Fernet(fernet_key.encode("utf-8"))
            schema_ready = True
            try:
                self._verify_schema()
            except Exception:
                schema_ready = False
            if not schema_ready:
                self.close()
                raise ConfigError(
                    "Secret schema is unavailable or incompatible"
                ) from None
        except BaseException:
            self.close()
            raise

    def _verify_schema(self) -> None:
        """Verify the provisioned secret table without acquiring DDL authority."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT secret_key, secret_value, is_encrypted, updated_at "
                f"FROM {self.TABLE_NAME} WHERE secret_key = %s",
                ("__pg_llm_batch_schema_probe__",),
            )

'''

SECRET_TABLE = '''CREATE TABLE IF NOT EXISTS com_secrets (
    secret_key TEXT PRIMARY KEY,
    secret_value TEXT NOT NULL,
    is_encrypted BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
'''

DEFAULT_SEED_SQL = '''

-- Provision built-in configuration only at the explicit schema boundary.
-- Existing operator values are never overwritten during upgrades or replay.
INSERT INTO com_config (config_key, config_value, config_description)
VALUES
    ('batch_size.min', '100', 'Batch request size limit'),
    ('batch_size.default', '50000', 'Batch request size limit'),
    ('batch_size.max', '50000', 'Batch request size limit'),
    ('token_limits.per_batch', '5000000000', 'Token count limits'),
    ('token_limits.per_request', '128000', 'Token count limits'),
    ('token_limits.buffer_percentage', '5', 'Token count limits'),
    ('azure_limits.max_records_per_file', '100000', 'Batch upload constraints'),
    ('azure_limits.max_bytes_per_file', '209715200', 'Batch upload constraints'),
    ('azure_limits.max_files_per_job', '500', 'Batch upload constraints'),
    ('optimization.auto_split', 'true', 'Optimization features'),
    ('optimization.smart_batching', 'true', 'Optimization features')
ON CONFLICT (config_key) DO NOTHING;
'''


def _replace_runtime_blocks(source: str) -> str:
    """Replace constructor provisioning with read-only schema capability probes."""
    config_class = source.index("class PostgresConfigStore:")
    config_start = source.index(CONFIG_CONNECTION, config_class)
    config_end = source.index(CONFIG_LOAD_METHOD, config_start)
    source = source[:config_start] + CONFIG_RUNTIME_BLOCK + source[config_end:]

    secret_class = source.index(SECRET_CLASS)
    secret_start = source.index(CONFIG_CONNECTION, secret_class)
    secret_end = source.index(SECRET_ENCODE_METHOD, secret_start)
    return source[:secret_start] + SECRET_RUNTIME_BLOCK + source[secret_end:]


def _seed_schema(schema: str) -> str:
    """Seed built-in configuration at explicit provisioning without overwrites."""
    if DEFAULT_SEED_SQL.strip() in schema:
        return schema
    if schema.count(SECRET_TABLE) != 1:
        raise RuntimeError("secret table provisioning anchor changed")
    return schema.replace(SECRET_TABLE, SECRET_TABLE + DEFAULT_SEED_SQL, 1)


def main() -> int:
    """Write the deterministic candidate into the ephemeral checkout only."""
    source = CONFIG_PATH.read_text(encoding="utf-8")
    if "def _ensure_defaults" not in source or source.count("def _ensure_table") < 2:
        raise RuntimeError("runtime provisioning source is not the expected RED revision")
    repaired_source = _replace_runtime_blocks(source)
    if "def _ensure_defaults" in repaired_source or "CREATE TABLE IF NOT EXISTS" in repaired_source:
        raise RuntimeError("runtime provisioning authority remained in config.py")
    CONFIG_PATH.write_text(repaired_source, encoding="utf-8")

    schema = _seed_schema(PACKAGE_SCHEMA_PATH.read_text(encoding="utf-8"))
    PACKAGE_SCHEMA_PATH.write_text(schema, encoding="utf-8")
    DOCKER_SCHEMA_PATH.write_text(schema, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
