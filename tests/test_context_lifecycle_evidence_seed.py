# SPDX-License-Identifier: Apache-2.0
"""Release-independent privacy and replay contracts for Context lifecycle evidence."""

from __future__ import annotations

from dataclasses import fields, replace

import pytest

from pg_llm_batch.context_lifecycle_evidence import (
    ContextLifecycleEvidenceError,
    ContextLifecycleEvidenceSeed,
    require_context_lifecycle_replay_identity,
    require_context_lifecycle_scope_continuity,
    validate_context_lifecycle_evidence_seed,
)


VALID = ContextLifecycleEvidenceSeed(
    evidence_id="batch.lifecycle.01HZZZZZZZZZZZZZZZZZZZZZZZ",
    event_type="batch.lifecycle.completed",
    tenant_scope_sha256="1" * 64,
    subject_ref_sha256="2" * 64,
    authority_ref_sha256="3" * 64,
    origin_ref_sha256="4" * 64,
    truth_status="observed",
    valid_time="2026-09-03T07:00:00Z",
    system_time="2026-09-03T07:00:01.123456Z",
    provenance_ref_sha256="5" * 64,
    evidence_ref_sha256="6" * 64,
)


def test_context_lifecycle_seed_has_no_arbitrary_content_surface() -> None:
    """The ACL seed cannot carry prompts, provider bodies, credentials, or metadata."""
    assert {field.name for field in fields(ContextLifecycleEvidenceSeed)} == {
        "evidence_id",
        "event_type",
        "tenant_scope_sha256",
        "subject_ref_sha256",
        "authority_ref_sha256",
        "origin_ref_sha256",
        "truth_status",
        "valid_time",
        "system_time",
        "provenance_ref_sha256",
        "evidence_ref_sha256",
    }


def test_context_lifecycle_seed_accepts_bounded_content_free_identity() -> None:
    validated = validate_context_lifecycle_evidence_seed(VALID)

    assert validated == VALID
    assert validated is not VALID


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_id", "prompt body with spaces"),
        ("event_type", "Batch.Completed"),
        ("tenant_scope_sha256", "A" * 64),
        ("subject_ref_sha256", "2" * 63),
        ("authority_ref_sha256", None),
        ("origin_ref_sha256", True),
        ("truth_status", "trusted"),
        ("valid_time", "2026-09-03 07:00:00Z"),
        ("system_time", "2026-09-03T07:00:00+09:00"),
        ("system_time", "2026-02-31T07:00:00Z"),
        ("provenance_ref_sha256", "secret-value"),
        ("evidence_ref_sha256", "6" * 65),
    ],
)
def test_context_lifecycle_seed_rejects_malformed_or_open_authority(
    field: str,
    value: object,
) -> None:
    candidate = replace(VALID, **{field: value})  # type: ignore[arg-type]

    with pytest.raises(ContextLifecycleEvidenceError) as raised:
        validate_context_lifecycle_evidence_seed(candidate)

    assert str(raised.value) == "invalid context lifecycle evidence"
    assert str(value) not in str(raised.value)


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-09-03T07:00:01.1Z",
        "2026-09-03T07:00:01.123Z",
        "2026-09-03T07:00:01.000000Z",
    ],
)
def test_context_lifecycle_seed_rejects_noncanonical_timestamp_aliases(
    timestamp: str,
) -> None:
    """Equivalent instants cannot acquire multiple lifecycle evidence identities."""
    candidate = replace(VALID, system_time=timestamp)

    with pytest.raises(
        ContextLifecycleEvidenceError,
        match="invalid context lifecycle evidence",
    ):
        validate_context_lifecycle_evidence_seed(candidate)


def test_context_lifecycle_seed_rejects_shaped_object_before_member_access() -> None:
    class HostileEvidence:
        @property
        def evidence_id(self) -> str:
            raise AssertionError("untrusted member accessed")

    with pytest.raises(
        ContextLifecycleEvidenceError,
        match="invalid context lifecycle evidence",
    ):
        validate_context_lifecycle_evidence_seed(  # type: ignore[arg-type]
            HostileEvidence()
        )


def test_context_lifecycle_seed_rejects_deleted_required_member() -> None:
    candidate = replace(VALID)
    object.__delattr__(candidate, "origin_ref_sha256")

    with pytest.raises(
        ContextLifecycleEvidenceError,
        match="invalid context lifecycle evidence",
    ):
        validate_context_lifecycle_evidence_seed(candidate)


def test_context_lifecycle_replay_accepts_only_exact_duplicate_identity() -> None:
    replay = require_context_lifecycle_replay_identity(
        existing=VALID,
        candidate=replace(VALID),
    )

    assert replay == VALID
    assert replay is not VALID


def test_context_lifecycle_replay_rejects_different_event_identity() -> None:
    different_event = replace(
        VALID,
        evidence_id="batch.lifecycle.01J00000000000000000000000",
    )

    with pytest.raises(
        ContextLifecycleEvidenceError,
        match="invalid context lifecycle evidence",
    ):
        require_context_lifecycle_replay_identity(
            existing=VALID,
            candidate=different_event,
        )


def test_context_lifecycle_replay_rejects_same_id_with_conflicting_evidence() -> None:
    conflicting = replace(VALID, evidence_ref_sha256="7" * 64)

    with pytest.raises(
        ContextLifecycleEvidenceError,
        match="invalid context lifecycle evidence",
    ):
        require_context_lifecycle_replay_identity(
            existing=VALID,
            candidate=conflicting,
        )


def test_context_lifecycle_scope_continuity_preserves_tenant_subject_and_authority() -> None:
    next_event = replace(
        VALID,
        evidence_id="batch.lifecycle.01J00000000000000000000000",
        event_type="batch.lifecycle.archived",
        valid_time="2026-09-03T08:00:00Z",
        system_time="2026-09-03T08:00:01Z",
        provenance_ref_sha256="8" * 64,
        evidence_ref_sha256="9" * 64,
    )

    admitted = require_context_lifecycle_scope_continuity(
        previous=VALID,
        current=next_event,
    )

    assert admitted == next_event
    assert admitted is not next_event


@pytest.mark.parametrize(
    "field",
    [
        "tenant_scope_sha256",
        "subject_ref_sha256",
        "authority_ref_sha256",
        "origin_ref_sha256",
    ],
)
def test_context_lifecycle_scope_continuity_rejects_authority_drift(field: str) -> None:
    current = replace(
        VALID,
        evidence_id="batch.lifecycle.01J00000000000000000000000",
        **{field: "a" * 64},
    )

    with pytest.raises(
        ContextLifecycleEvidenceError,
        match="invalid context lifecycle evidence",
    ):
        require_context_lifecycle_scope_continuity(
            previous=VALID,
            current=current,
        )
