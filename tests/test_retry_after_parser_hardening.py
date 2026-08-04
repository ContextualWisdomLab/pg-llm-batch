# SPDX-License-Identifier: Apache-2.0
"""Regression tests for hostile and non-standard Retry-After values."""

from __future__ import annotations

from datetime import datetime, timezone

from pg_llm_batch import batch_api_client as client_mod


def test_oversized_ascii_delta_is_classified_as_excessive() -> None:
    """A huge ASCII delta must not hit Python's bounded-int conversion error."""
    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    assert client_mod._parse_retry_after("9" * 5000, now) == float("inf")


def test_non_ascii_decimal_digits_are_not_rfc_delta_seconds() -> None:
    """RFC delay-seconds use ASCII DIGIT, not arbitrary Unicode decimals."""
    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    assert client_mod._parse_retry_after("１２", now) is None
