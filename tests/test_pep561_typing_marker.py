# SPDX-License-Identifier: Apache-2.0
"""Regression contract for standard inline typing distribution metadata."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "pg_llm_batch"


def test_inline_typed_package_declares_pep561_marker() -> None:
    """Declare package-owned inline annotations through the standard marker."""
    marker = PACKAGE_ROOT / "py.typed"
    assert marker.is_file()
    assert marker.read_bytes() == b""
