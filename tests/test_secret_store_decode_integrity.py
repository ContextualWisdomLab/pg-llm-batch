# SPDX-License-Identifier: Apache-2.0
"""Regression tests for fail-closed persisted secret decoding."""

from __future__ import annotations

import pytest

from pg_llm_batch.config import SecretStore
from pg_llm_batch.exceptions import ConfigError


def _store_with_fernet(fernet: object | None) -> SecretStore:
    """Build a database-free SecretStore instance for decode-boundary tests."""
    store = SecretStore.__new__(SecretStore)
    store._fernet = fernet
    return store


def test_corrupt_base64_secret_fails_closed_without_silent_normalization() -> None:
    """Invalid persisted Base64 must not decode to a different plaintext value."""
    store = _store_with_fernet(None)

    with pytest.raises(ConfigError, match="Stored secret could not be decoded") as caught:
        store._decode("%%%", False)

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
