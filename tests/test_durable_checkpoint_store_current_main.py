# SPDX-License-Identifier: Apache-2.0
"""Fail-first contracts for durable checkpoint persistence on current main."""

from __future__ import annotations

import pytest

from pg_llm_batch.checkpoint_store import (
    PostgresBatchResultCheckpointStore,
    validate_checkpoint_consumer_name,
)
from pg_llm_batch.exceptions import ConfigError, ValidationError


def test_checkpoint_store_requires_an_explicit_nonblank_database_target() -> None:
    """Durable checkpoint persistence must never inherit an ambiguous DB target."""
    with pytest.raises(ConfigError, match="must be provided explicitly"):
        PostgresBatchResultCheckpointStore("   ")


def test_checkpoint_consumer_identity_is_bounded_and_host_selected() -> None:
    """Consumer identity must remain a finite host-selected storage key."""
    assert validate_checkpoint_consumer_name("worker-1") == "worker-1"

    with pytest.raises(ValidationError):
        validate_checkpoint_consumer_name("tenant supplied value with spaces")
