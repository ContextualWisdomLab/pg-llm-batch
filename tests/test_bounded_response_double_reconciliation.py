# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for protected-main bounded response-double reconciliation."""

from __future__ import annotations

from pathlib import Path


HELPER_PATH = Path("tests/bounded_response_double.py")
LOCAL_STREAM_MARKERS = {
    Path("tests/test_remote_batch_identity_contract.py"): "class _ByteStream:",
    Path("tests/test_remote_batch_lifecycle.py"): "class _ByteStream:",
    Path("tests/test_remote_batch_metadata_contract.py"): "class _MetadataByteStream:",
    Path("tests/test_remote_batch_state_contracts.py"): "class _ProviderByteStream:",
}


def test_shared_bounded_response_double_matches_protected_main_contract() -> None:
    """The reconciled branch retains the shared bounded byte-stream test helper."""
    helper = HELPER_PATH.read_text(encoding="utf-8")

    assert "class BoundedJsonByteStream:" in helper
    assert "async def iter_chunked(self, size: int)" in helper
    assert "bounded response chunk size must be a positive integer" in helper
    assert "def bind_bounded_json_response(" in helper
    assert "response.content_length = len(content.payload_bytes)" in helper


def test_tenant_specific_doubles_preserve_equivalent_bounded_streaming() -> None:
    """Conflict resolution may retain stricter local doubles instead of duplicating them."""
    for path, class_marker in LOCAL_STREAM_MARKERS.items():
        source = path.read_text(encoding="utf-8")
        assert class_marker in source, path
        assert "async def iter_chunked(self, size: int)" in source, path
        assert "response.json() must not bypass bounded streaming" in source, path
