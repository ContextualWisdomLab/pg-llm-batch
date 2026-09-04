# SPDX-License-Identifier: Apache-2.0
"""Regression tests for fail-closed persisted secret decoding."""

from __future__ import annotations

import pytest

from pg_llm_batch.config import SecretStore
from pg_llm_batch.exceptions import ConfigError


def _store_with_fernet(fernet: object | None) -> SecretStore:
    """Build a database-free SecretStore instance for crypto-boundary tests."""
    store = SecretStore.__new__(SecretStore)
    store._fernet = fernet
    return store


def test_unencrypted_persisted_secret_is_rejected_without_base64_decode() -> None:
    """Legacy Base64 state must never become runtime plaintext after hardening."""
    store = _store_with_fernet(None)

    with pytest.raises(ConfigError, match="required encryption policy") as caught:
        store._decode("Zm9v", False)

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_encode_without_fernet_key_fails_closed() -> None:
    """A broken internal invariant must not re-enable unencrypted persistence."""
    store = _store_with_fernet(None)

    with pytest.raises(ConfigError, match="encryption key is unavailable") as caught:
        store._encode("plaintext")

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_encrypted_decode_without_fernet_key_fails_closed() -> None:
    """Encrypted durable state cannot be read without its configured Fernet key."""
    store = _store_with_fernet(None)

    with pytest.raises(ConfigError, match="no Fernet key") as caught:
        store._decode("ciphertext", True)

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


class _FailingFernet:
    """Simulate lower-layer decrypt diagnostics that must never escape."""

    def decrypt(self, _token: bytes) -> bytes:
        """Raise a diagnostic containing content that must be discarded."""
        raise RuntimeError("sensitive-provider-or-ciphertext-diagnostic")


def test_encrypted_decode_failure_is_redacted_to_fixed_package_error() -> None:
    """Decrypt failures must not retain lower-layer secret-bearing diagnostics."""
    store = _store_with_fernet(_FailingFernet())

    with pytest.raises(ConfigError, match="Stored secret could not be decoded") as caught:
        store._decode("ciphertext", True)

    assert "sensitive-provider-or-ciphertext-diagnostic" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


class _PersistedSecretCursor:
    """Return one intentionally malformed persisted secret row."""

    def __enter__(self) -> _PersistedSecretCursor:
        """Enter the lightweight cursor context."""
        return self

    def __exit__(self, *_args: object) -> None:
        """Leave the lightweight cursor context."""

    def execute(self, *_args: object) -> None:
        """Accept the fixed package lookup query without side effects."""

    def fetchone(self) -> tuple[str, str]:
        """Return a text flag that must not be coerced into encryption authority."""
        return ("Zm9v", "false")


class _PersistedSecretConnection:
    """Provide the malformed persisted row to ``SecretStore.get_secret``."""

    def cursor(self) -> _PersistedSecretCursor:
        """Return the deterministic persisted-secret cursor."""
        return _PersistedSecretCursor()


def test_persisted_encryption_flag_type_is_not_coerced_before_validation() -> None:
    """A non-boolean durable encryption flag must fail closed as corrupt state."""
    store = _store_with_fernet(None)
    store._conn = _PersistedSecretConnection()

    with pytest.raises(ConfigError, match="Stored secret could not be decoded") as caught:
        store.get_secret("gateway_api_key")

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
