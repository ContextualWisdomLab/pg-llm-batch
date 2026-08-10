# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Database-backed configuration and secret stores.

This module replaces the ~75 ``os.getenv`` reads in the upstream app. All
tunables and secrets live in Postgres KV tables (``com_config`` for plain
config, ``com_secrets`` for credentials). The only permitted bootstrap
transport is the DSN itself (see :func:`pg_llm_batch.bootstrap.resolve_dsn`)
plus an optional Fernet key used to decrypt secrets at rest.

Two-word snake_case table names satisfy the org DB naming rule:
``com_config`` and ``com_secrets``.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Dict, Iterable, Optional, Tuple, Type

from .exceptions import ConfigError

try:  # pragma: no cover - optional dependency
    import psycopg  # type: ignore
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore

try:  # pragma: no cover - optional dependency
    from cryptography.fernet import Fernet, InvalidToken  # type: ignore
except ImportError:  # pragma: no cover
    Fernet = None  # type: ignore
    InvalidToken = Exception  # type: ignore

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_TREE: Dict[str, Dict[str, Any]] = {
    "batch_size": {
        "min": 100,
        "default": 50000,
        "max": 50000,
        "description": "Batch request size limit",
    },
    "token_limits": {
        "per_batch": 5_000_000_000,
        "per_request": 128_000,
        "buffer_percentage": 5,
        "description": "Token count limits",
    },
    "azure_limits": {
        "max_records_per_file": 100_000,
        "max_bytes_per_file": 200 * 1024 * 1024,
        "max_files_per_job": 500,
        "description": "Batch upload constraints",
    },
    "optimization": {
        "auto_split": True,
        "smart_batching": True,
        "description": "Optimization features",
    },
}


def _build_default_index(
    tree: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Flatten the default config tree into a ``category.key`` lookup with type metadata."""
    index: Dict[str, Dict[str, Any]] = {}
    for category, settings in tree.items():
        category_description = settings.get("description")
        for key, value in settings.items():
            if key == "description":
                continue
            full_key = f"{category}.{key}"
            index[full_key] = {
                "category": category,
                "key": key,
                "value": value,
                "type": type(value),
                "description": category_description or full_key,
            }
    return index


DEFAULT_CONFIG_INDEX = _build_default_index(DEFAULT_CONFIG_TREE)


def _serialize_value(value: Any) -> str:
    """Serialize a config value to text (JSON for dict/list/bool, else ``str``)."""
    if isinstance(value, (dict, list, bool)):
        return json.dumps(value)
    return str(value)


def _deserialize_value(full_key: str, raw: str) -> Any:
    """Coerce a stored text value back to the default's type, or fall back on error."""
    item = DEFAULT_CONFIG_INDEX.get(full_key)
    target_type: Optional[Type[Any]] = item["type"] if item else None

    if target_type in (dict, list):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return item["value"] if item else {}
    if target_type is bool:
        lowered = raw.lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
        return bool(raw)
    if target_type is int:
        try:
            return int(raw)
        except ValueError:
            return item["value"] if item else 0
    if target_type is float:
        try:
            return float(raw)
        except ValueError:
            return item["value"] if item else 0.0
    return raw


def _default_value(category: str, key: str, fallback: Any) -> Any:
    """Return the built-in default for ``category.key`` or the caller's fallback."""
    item = DEFAULT_CONFIG_INDEX.get(f"{category}.{key}")
    return item["value"] if item else fallback


def _split_full_key(full_key: str) -> Tuple[str, str]:
    """Split a ``category.key`` string, defaulting the category to ``global``."""
    if "." in full_key:
        parts = full_key.split(".", 1)
        return parts[0], parts[1]
    return "global", full_key


def _validated_postgres_dsn(value: Any) -> str:
    """Require an explicit nonblank database target without rewriting it."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            "A Postgres DSN must be provided explicitly (no os.getenv for config)"
        )
    return value


class PostgresConfigStore:
    """PostgreSQL-backed KV configuration store (``com_config`` table)."""

    TABLE_NAME = "com_config"

    def __init__(self, dsn: str) -> None:
        """Connect, initialize the cache, and release partial setup on failure."""
        if psycopg is None:
            raise ConfigError("psycopg is required for PostgresConfigStore")
        self.dsn = _validated_postgres_dsn(dsn)
        self._conn = psycopg.connect(self.dsn)
        try:
            self._conn.autocommit = True
            self.cache: Dict[str, Dict[str, Any]] = {}
            self._ensure_table()
            self._ensure_defaults()
            self._load_cache()
        except BaseException:
            self.close()
            raise

    def _ensure_table(self) -> None:
        """Create the ``com_config`` table if it does not already exist."""
        with self._conn.cursor() as cur:
            cur.execute(  # nosemgrep -- formatted-sql-query / sqlalchemy-execute-raw-query FP: only the fixed class constant TABLE_NAME ("com_config") is interpolated; every value is bound via %s placeholders.
                f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                    config_key TEXT PRIMARY KEY,
                    config_value TEXT NOT NULL,
                    config_description TEXT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

    def _ensure_defaults(self) -> None:
        """Insert missing default config rows without overwriting existing ones."""
        with self._conn.cursor() as cur:
            for item in DEFAULT_CONFIG_INDEX.values():
                cur.execute(  # nosemgrep -- sqlalchemy-execute-raw-query FP: only the fixed TABLE_NAME constant is interpolated; all values are bound via %s placeholders.
                    f"""
                    INSERT INTO {self.TABLE_NAME}
                        (config_key, config_value, config_description)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (config_key) DO NOTHING
                    """,
                    (
                        f"{item['category']}.{item['key']}",
                        _serialize_value(item["value"]),
                        item["description"],
                    ),
                )

    def _load_cache(self) -> None:
        """Reload the in-memory cache from every row in the config table."""
        self.cache.clear()
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT config_key, config_value FROM {self.TABLE_NAME}")  # nosemgrep -- formatted-sql-query / sqlalchemy-execute-raw-query FP: only the fixed TABLE_NAME constant is interpolated; no user input reaches the query.
            for config_key, config_value in cur.fetchall():
                category, key = _split_full_key(config_key)
                value = _deserialize_value(config_key, config_value)
                self.cache.setdefault(category, {})[key] = value

    def get(self, category: str, key: str, default: Any = None) -> Any:
        """Return a typed configuration value, falling back to its default."""
        if category in self.cache and key in self.cache[category]:
            return self.cache[category][key]
        full_key = f"{category}.{key}"
        with self._conn.cursor() as cur:
            cur.execute(  # nosemgrep -- sqlalchemy-execute-raw-query FP: only the fixed TABLE_NAME constant is interpolated; the lookup value is bound via a %s placeholder.
                f"SELECT config_value FROM {self.TABLE_NAME} WHERE config_key = %s",
                (full_key,),
            )
            row = cur.fetchone()
        if row:
            value = _deserialize_value(full_key, row[0])
            self.cache.setdefault(category, {})[key] = value
            return value
        return _default_value(category, key, default)

    def set(self, category: str, key: str, value: Any) -> None:
        """Persist and cache a typed configuration value."""
        full_key = f"{category}.{key}"
        serialized = _serialize_value(value)
        item = DEFAULT_CONFIG_INDEX.get(full_key)
        description = item["description"] if item else full_key
        with self._conn.cursor() as cur:
            cur.execute(  # nosemgrep -- sqlalchemy-execute-raw-query FP: only the fixed TABLE_NAME constant is interpolated; all values are bound via %s placeholders.
                f"""
                INSERT INTO {self.TABLE_NAME}
                    (config_key, config_value, config_description)
                VALUES (%s, %s, %s)
                ON CONFLICT (config_key) DO UPDATE
                SET config_value = EXCLUDED.config_value,
                    config_description = EXCLUDED.config_description,
                    updated_at = NOW()
                """,
                (full_key, serialized, description),
            )
        self.cache.setdefault(category, {})[key] = value

    def show_config(self) -> Iterable[Tuple[str, str, Any]]:
        """Yield all configuration entries in stable key order."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT config_key, config_value FROM {self.TABLE_NAME} "
                "ORDER BY config_key"
            )
            rows = cur.fetchall()
        for config_key, config_value in rows:
            category, key = _split_full_key(config_key)
            yield category, key, _deserialize_value(config_key, config_value)

    def close(self) -> None:
        """Close the backing PostgreSQL connection if it is open."""
        conn = getattr(self, "_conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._conn = None


class SecretStore:
    """PostgreSQL-backed secret store (``com_secrets`` table).

    Values are Fernet-encrypted at rest when a key is supplied. Without a key,
    values are base64-obfuscated and a warning is logged; that fallback is
    acceptable only for local/dev containers and is not encryption. When a
    Fernet key is configured, missing ``cryptography`` support fails closed
    instead of silently downgrading that explicit encryption request.
    """

    TABLE_NAME = "com_secrets"

    def __init__(self, dsn: str, fernet_key: Optional[str] = None) -> None:
        """Connect, configure encryption, and release partial setup on failure."""
        if psycopg is None:
            raise ConfigError("psycopg is required for SecretStore")
        self.dsn = _validated_postgres_dsn(dsn)
        self._conn = psycopg.connect(self.dsn)
        try:
            self._conn.autocommit = True
            self._fernet = None
            if fernet_key and Fernet is not None:
                self._fernet = Fernet(fernet_key.encode("utf-8"))
            elif fernet_key and Fernet is None:
                raise ConfigError(
                    "cryptography is required when a Fernet key is configured"
                )
            self._ensure_table()
        except BaseException:
            self.close()
            raise

    def _ensure_table(self) -> None:
        """Create the ``com_secrets`` table if it does not already exist."""
        with self._conn.cursor() as cur:
            cur.execute(  # nosemgrep -- formatted-sql-query / sqlalchemy-execute-raw-query FP: only the fixed class constant TABLE_NAME ("com_secrets") is interpolated; every value is bound via %s placeholders.
                f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                    secret_key TEXT PRIMARY KEY,
                    secret_value TEXT NOT NULL,
                    is_encrypted BOOLEAN NOT NULL DEFAULT FALSE,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

    def _encode(self, raw: str) -> Tuple[str, bool]:
        """Encode a secret for storage and return whether it is encrypted."""
        if self._fernet is not None:
            return self._fernet.encrypt(raw.encode("utf-8")).decode("utf-8"), True
        logger.warning(  # nosemgrep -- python-logger-credential-disclosure FP: the message text contains the word "secret", but the only logged argument is the literal mask "***"; no secret value is ever logged.
            "No Fernet key configured; secret '%s' stored base64-obfuscated only.",
            "***",
        )
        return base64.b64encode(raw.encode("utf-8")).decode("utf-8"), False

    def _decode(self, stored: str, is_encrypted: bool) -> str:
        """Decrypt or de-obfuscate a stored secret."""
        if is_encrypted:
            if self._fernet is None:
                raise ConfigError(
                    "Secret is encrypted but no Fernet key is configured to decrypt it"
                )
            decrypted: Optional[str]
            try:
                decrypted = self._fernet.decrypt(stored.encode("utf-8")).decode("utf-8")
            except (InvalidToken, UnicodeError):
                decrypted = None
            if decrypted is None:
                raise ConfigError("stored encrypted secret is invalid")
            return decrypted
        decoded: Optional[str]
        try:
            decoded = base64.b64decode(
                stored.encode("utf-8"), validate=True
            ).decode("utf-8")
        except ValueError:
            decoded = None
        if decoded is None:
            raise ConfigError("stored secret encoding is invalid")
        return decoded

    def set_secret(self, key: str, value: str) -> None:
        """Encrypt or obfuscate and persist a secret value."""
        encoded, is_encrypted = self._encode(value)
        with self._conn.cursor() as cur:
            cur.execute(  # nosemgrep -- sqlalchemy-execute-raw-query FP: only the fixed TABLE_NAME constant is interpolated; all values are bound via %s placeholders.
                f"""
                INSERT INTO {self.TABLE_NAME} (secret_key, secret_value, is_encrypted)
                VALUES (%s, %s, %s)
                ON CONFLICT (secret_key) DO UPDATE
                SET secret_value = EXCLUDED.secret_value,
                    is_encrypted = EXCLUDED.is_encrypted,
                    updated_at = NOW()
                """,
                (key, encoded, is_encrypted),
            )

    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Return a decoded secret or the supplied default when absent."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT secret_value, is_encrypted FROM {self.TABLE_NAME} "
                "WHERE secret_key = %s",
                (key,),
            )
            row = cur.fetchone()
        if not row:
            return default
        return self._decode(row[0], bool(row[1]))

    def require_secret(self, key: str) -> str:
        """Return a decoded secret or raise when the key is absent."""
        value = self.get_secret(key)
        if value is None:
            raise ConfigError(
                f"Required secret '{key}' is not present in {self.TABLE_NAME}. "
                "Seed it via `python -m pg_llm_batch config set-secret`."
            )
        return value

    def close(self) -> None:
        """Close the backing PostgreSQL connection if it is open."""
        conn = getattr(self, "_conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._conn = None


def get_config_store(dsn: str) -> PostgresConfigStore:
    """Construct a config store from an explicit DSN."""
    return PostgresConfigStore(dsn)