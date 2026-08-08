# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for protected-main bounded response-double reconciliation."""

from __future__ import annotations

from pathlib import Path


HELPER_PATH = Path("tests/bounded_response_double.py")
RESPONSE_DOUBLE_PATHS = (
    Path("tests/test_remote_batch_identity_contract.py"),
    Path("tests/test_remote_batch_lifecycle.py"),
    Path("tests/test_remote_batch_metadata_contract.py"),
    Path("tests/test_remote_batch_state_contracts.py"),
)


def test_shared_bounded_response_double_matches_protected_main_contract() -> None:
    """The reconciled branch retains the shared bounded byte-stream test helper."""
    helper = HELPER_PATH.read_text(encoding="utf-8")

    assert "class BoundedJsonByteStream:" in helper
    assert "async def iter_chunked(self, size: int)" in helper
    assert "bounded response chunk size must be a positive integer" in helper
    assert "def bind_bounded_json_response(" in helper
    assert "response.content_length = len(content.payload_bytes)" in helper


def test_lifecycle_response_doubles_use_the_shared_bounded_helper() -> None:
    """Conflicting lifecycle test doubles converge on the protected-main helper."""
    import_line = (
        "from tests.bounded_response_double import bind_bounded_json_response"
    )
    for path in RESPONSE_DOUBLE_PATHS:
        source = path.read_text(encoding="utf-8")
        assert import_line in source, path
        assert "bind_bounded_json_response(self, payload)" in source, path
