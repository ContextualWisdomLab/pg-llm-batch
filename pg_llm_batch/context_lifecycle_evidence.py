# SPDX-License-Identifier: Apache-2.0
"""Prepare privacy-minimized lifecycle evidence for a future Context Fabric ACL.

This module is deliberately release-independent. It validates a fixed, content-free
set of pg-llm-batch lifecycle identities that a later adapter may translate through
an independently verified released Context Assertion/CloudEvent contract. It does
not serialize an unreleased Context Graph schema, grant publication authority, or
accept prompts, responses, provider bodies, credentials, arbitrary metadata, or user
content.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re


_OPAQUE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_EVENT_TYPE_PATTERN = re.compile(r"[a-z][a-z0-9._:-]{0,127}\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_UTC_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z"
)
_TRUTH_STATUSES = frozenset(
    {
        "authoritative",
        "observed",
        "inferred",
        "proposed",
        "superseded",
        "rejected",
    }
)
_ERROR_MESSAGE = "invalid context lifecycle evidence"


class ContextLifecycleEvidenceError(ValueError):
    """Report invalid lifecycle evidence without reflecting caller-controlled data."""


@dataclass(frozen=True, slots=True)
class ContextLifecycleEvidenceSeed:
    """Carry only content-free identities needed by a future released adapter.

    Reference-like values are represented by SHA-256 identities instead of raw
    tenant, subject, authority, origin, provenance, or evidence payloads. This keeps
    the pre-release ACL seam useful for continuity and replay checks without copying
    an unreleased Context Fabric wire schema or widening routine evidence into a
    business-content transport.

    ``valid_time`` and ``system_time`` are distinct canonical UTC timestamps. No
    ordering is imposed because retrospective observations may legitimately be
    recorded after their business-valid time.
    """

    evidence_id: str
    event_type: str
    tenant_scope_sha256: str
    subject_ref_sha256: str
    authority_ref_sha256: str
    origin_ref_sha256: str
    truth_status: str
    valid_time: str
    system_time: str
    provenance_ref_sha256: str
    evidence_ref_sha256: str


def _invalid_evidence() -> ContextLifecycleEvidenceError:
    """Build the fixed non-reflecting validation error."""
    return ContextLifecycleEvidenceError(_ERROR_MESSAGE)


def _validate_opaque_id(value: object) -> str:
    """Return one bounded opaque identity token with no whitespace or path syntax."""
    if type(value) is not str or _OPAQUE_ID_PATTERN.fullmatch(value) is None:
        raise _invalid_evidence()
    return value


def _validate_event_type(value: object) -> str:
    """Return one bounded lower-case event classification token."""
    if type(value) is not str or _EVENT_TYPE_PATTERN.fullmatch(value) is None:
        raise _invalid_evidence()
    return value


def _validate_sha256(value: object) -> str:
    """Return one exact lower-case SHA-256 identity without coercion."""
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        raise _invalid_evidence()
    return value


def _validate_truth_status(value: object) -> str:
    """Return one closed Context truth/disposition status used by the ACL seed."""
    if type(value) is not str or value not in _TRUTH_STATUSES:
        raise _invalid_evidence()
    return value


def _validate_utc_timestamp(value: object) -> str:
    """Return one canonical UTC timestamp with seconds and optional microseconds."""
    if type(value) is not str or _UTC_TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise _invalid_evidence()
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except (ValueError, OverflowError):
        raise _invalid_evidence() from None
    return value


def validate_context_lifecycle_evidence_seed(
    evidence: ContextLifecycleEvidenceSeed,
) -> ContextLifecycleEvidenceSeed:
    """Snapshot and validate one release-independent lifecycle evidence seed.

    Exact package ownership is established before member access so shaped objects
    cannot execute caller behavior. Every member is then captured once and validated
    before a fresh immutable value is returned. The result remains only pg-owned ACL
    input; it cannot satisfy released Context Assertion admission or publication.

    Args:
        evidence: Candidate content-free lifecycle evidence.

    Returns:
        A fresh validated evidence snapshot.

    Raises:
        ContextLifecycleEvidenceError: If any identity or semantic field is invalid.
    """
    if type(evidence) is not ContextLifecycleEvidenceSeed:
        raise _invalid_evidence()

    try:
        evidence_id = evidence.evidence_id
        event_type = evidence.event_type
        tenant_scope_sha256 = evidence.tenant_scope_sha256
        subject_ref_sha256 = evidence.subject_ref_sha256
        authority_ref_sha256 = evidence.authority_ref_sha256
        origin_ref_sha256 = evidence.origin_ref_sha256
        truth_status = evidence.truth_status
        valid_time = evidence.valid_time
        system_time = evidence.system_time
        provenance_ref_sha256 = evidence.provenance_ref_sha256
        evidence_ref_sha256 = evidence.evidence_ref_sha256
    except AttributeError:
        raise _invalid_evidence() from None

    return ContextLifecycleEvidenceSeed(
        evidence_id=_validate_opaque_id(evidence_id),
        event_type=_validate_event_type(event_type),
        tenant_scope_sha256=_validate_sha256(tenant_scope_sha256),
        subject_ref_sha256=_validate_sha256(subject_ref_sha256),
        authority_ref_sha256=_validate_sha256(authority_ref_sha256),
        origin_ref_sha256=_validate_sha256(origin_ref_sha256),
        truth_status=_validate_truth_status(truth_status),
        valid_time=_validate_utc_timestamp(valid_time),
        system_time=_validate_utc_timestamp(system_time),
        provenance_ref_sha256=_validate_sha256(provenance_ref_sha256),
        evidence_ref_sha256=_validate_sha256(evidence_ref_sha256),
    )


def require_context_lifecycle_replay_identity(
    *,
    existing: ContextLifecycleEvidenceSeed,
    candidate: ContextLifecycleEvidenceSeed,
) -> ContextLifecycleEvidenceSeed:
    """Accept only an exact idempotent replay of one evidence identity.

    A duplicate event identifier is safe only when every content-free identity,
    truth/time semantic, and evidence digest is unchanged. A reused identifier with
    any drift is a conflicting replay and fails closed rather than being silently
    treated as a retry.

    Args:
        existing: Previously admitted lifecycle evidence.
        candidate: Candidate retry or replay of that evidence.

    Returns:
        A fresh validated copy of the candidate when the replay is exact.

    Raises:
        ContextLifecycleEvidenceError: If either value is invalid or replay conflicts.
    """
    validated_existing = validate_context_lifecycle_evidence_seed(existing)
    validated_candidate = validate_context_lifecycle_evidence_seed(candidate)
    if (
        validated_existing.evidence_id != validated_candidate.evidence_id
        or validated_existing != validated_candidate
    ):
        raise _invalid_evidence()
    return validated_candidate


def require_context_lifecycle_scope_continuity(
    *,
    previous: ContextLifecycleEvidenceSeed,
    current: ContextLifecycleEvidenceSeed,
) -> ContextLifecycleEvidenceSeed:
    """Reject tenant, subject, authority, or origin drift across lifecycle evidence.

    Lifecycle state, truth disposition, timestamps, provenance, and evidence receipts
    may legitimately change between events. Tenant scope and the canonical subject,
    authority, and origin identities may not silently drift inside one lifecycle
    chain; callers that intend a different authority chain must establish it through
    a separate domain transition rather than this continuity helper.

    Args:
        previous: Earlier evidence in the same lifecycle chain.
        current: Later evidence proposed for that chain.

    Returns:
        A fresh validated copy of ``current`` when scope authority is unchanged.

    Raises:
        ContextLifecycleEvidenceError: If either value is invalid or scope drifts.
    """
    validated_previous = validate_context_lifecycle_evidence_seed(previous)
    validated_current = validate_context_lifecycle_evidence_seed(current)
    if (
        validated_previous.tenant_scope_sha256
        != validated_current.tenant_scope_sha256
        or validated_previous.subject_ref_sha256
        != validated_current.subject_ref_sha256
        or validated_previous.authority_ref_sha256
        != validated_current.authority_ref_sha256
        or validated_previous.origin_ref_sha256 != validated_current.origin_ref_sha256
    ):
        raise _invalid_evidence()
    return validated_current
