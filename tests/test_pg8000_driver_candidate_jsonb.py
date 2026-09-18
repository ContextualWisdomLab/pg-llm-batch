"""Candidate JSONB adaptation contract for the permissive PostgreSQL driver lane.

The pg8000 migration remains candidate-only until the exact artifact proves the
complete PostgreSQL, conninfo, RLS, recovery, packaging, SBOM, and provenance
contract. These tests pin only the JSONB parameter boundary needed by the
existing ``PostgresDriverPort.jsonb`` capability.
"""

from __future__ import annotations

import json
import math

import pytest

from pg_llm_batch.pg8000_driver_candidate_jsonb import (
    Pg8000CandidateJsonbError,
    adapt_pg8000_jsonb,
)


def test_candidate_jsonb_serializes_exact_json_semantics_for_dbapi_binding() -> None:
    """Return UTF-8 JSON text that pg8000 DB-API can bind to a JSONB cast."""
    payload = {
        "request_id": "opaque-1",
        "labels": ["한국어", "English", None],
        "enabled": True,
        "count": 3,
    }

    adapted = adapt_pg8000_jsonb(payload)

    assert type(adapted) is str
    assert adapted.encode("utf-8")
    assert json.loads(adapted) == payload
    assert payload["labels"] == ["한국어", "English", None]


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_candidate_jsonb_rejects_non_finite_numbers(value: float) -> None:
    """Reject values PostgreSQL JSONB cannot represent as standards-compliant JSON."""
    with pytest.raises(Pg8000CandidateJsonbError, match="JSONB value is invalid"):
        adapt_pg8000_jsonb({"value": value})


def test_candidate_jsonb_rejects_unencodable_or_non_json_values() -> None:
    """Normalize invalid candidate payloads to one non-content-bearing error."""
    for value in ({"value": object()}, {"value": "\ud800"}):
        with pytest.raises(Pg8000CandidateJsonbError, match="JSONB value is invalid"):
            adapt_pg8000_jsonb(value)
