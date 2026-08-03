# SPDX-License-Identifier: Apache-2.0
"""Tests for collision-resistant in-memory payload identifiers."""

from __future__ import annotations

from types import SimpleNamespace

from pg_llm_batch import orchestrator as orch_mod
from pg_llm_batch.batch_api_client import _validate_resource_id
from pg_llm_batch.orchestrator import _new_payload_file_id


def test_payload_ids_use_the_complete_uuid_entropy(monkeypatch):
    """The generated identifier keeps all 32 UUID hexadecimal characters."""
    values = iter(
        [
            SimpleNamespace(hex="0" * 32),
            SimpleNamespace(hex="f" * 32),
        ]
    )
    monkeypatch.setattr(orch_mod.uuid, "uuid4", lambda: next(values))

    first = _new_payload_file_id()
    second = _new_payload_file_id()

    assert first == f"file_{'0' * 32}"
    assert second == f"file_{'f' * 32}"
    assert len(first) == 37
    assert first != second
    assert _validate_resource_id(first, "file_id") == first
    assert _validate_resource_id(second, "file_id") == second
