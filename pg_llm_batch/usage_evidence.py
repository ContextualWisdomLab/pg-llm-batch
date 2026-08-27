# SPDX-License-Identifier: Apache-2.0
"""Build bounded deterministic usage-authority evidence without billing."""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum

_MAX_COUNT = 2**63 - 1
_MAX_IDENTIFIER_LENGTH = 128
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,127}\Z")


class UsageEvidenceError(ValueError):
    """Report a fail-closed usage-evidence validation error."""


class UsageAuthority(str, Enum):
    """Identify the authority class for one usage-evidence record."""

    LOCAL_MEASURED = "LOCAL_MEASURED"
    PROVIDER_REPORTED = "PROVIDER_REPORTED"
    HOST_RATE_ESTIMATE = "HOST_RATE_ESTIMATE"
    RECONCILED = "RECONCILED"


def _require_identifier(value: object) -> str:
    """Return one bounded opaque identifier or fail closed."""
    if type(value) is not str:
        raise UsageEvidenceError("invalid usage evidence identifier")
    if len(value) > _MAX_IDENTIFIER_LENGTH:
        raise UsageEvidenceError("invalid usage evidence identifier")
    if _IDENTIFIER_RE.fullmatch(value) is None:
        raise UsageEvidenceError("invalid usage evidence identifier")
    return value


def _optional_identifier(value: object | None) -> str | None:
    """Return a validated optional opaque identifier."""
    if value is None:
        return None
    return _require_identifier(value)


def _require_count(value: object) -> int:
    """Return a bounded non-negative integer count or fail closed."""
    if type(value) is not int or value < 0 or value > _MAX_COUNT:
        raise UsageEvidenceError("invalid usage evidence count")
    return value


def _optional_count(value: object | None) -> int | None:
    """Return a validated optional bounded count."""
    if value is None:
        return None
    return _require_count(value)


def build_usage_evidence(
    *,
    authority: UsageAuthority,
    tenant_scope_id: str,
    source_id: str,
    request_count: int,
    input_token_count: int | None = None,
    output_token_count: int | None = None,
    provider_alias: str | None = None,
    endpoint_alias: str | None = None,
    remote_batch_id: str | None = None,
) -> tuple[str, str]:
    """Return canonical JSON and SHA-256 identity for bounded usage evidence."""
    if type(authority) is not UsageAuthority:
        raise UsageEvidenceError("invalid usage evidence authority")

    payload = {
        "authority": authority.value,
        "endpoint_alias": _optional_identifier(endpoint_alias),
        "input_token_count": _optional_count(input_token_count),
        "output_token_count": _optional_count(output_token_count),
        "provider_alias": _optional_identifier(provider_alias),
        "remote_batch_id": _optional_identifier(remote_batch_id),
        "request_count": _require_count(request_count),
        "source_id": _require_identifier(source_id),
        "tenant_scope_id": _require_identifier(tenant_scope_id),
    }
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    evidence_sha256 = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return canonical_json, evidence_sha256
