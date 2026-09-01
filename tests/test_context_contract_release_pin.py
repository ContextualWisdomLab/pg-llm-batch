# SPDX-License-Identifier: Apache-2.0
"""Consumer contracts for immutable Context Fabric release pins."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pg_llm_batch.context_contract_release import (
    ContextContractReleasePin,
    ContextContractReleasePinError,
    ContextContractReleaseVerification,
    require_context_contract_release_compatibility,
    require_context_contract_release_ready,
    validate_context_contract_release_pin,
)


VALID_PIN = ContextContractReleasePin(
    distribution_name="future-context-contract-package",
    release_version="0.1.0",
    source_commit="a" * 40,
    distribution_sha256="b" * 64,
    profile_name="context-assertion-event-semantics.v1.json",
    profile_sha256="c" * 64,
    resource_name="context-assertion.schema.json",
    resource_sha256="d" * 64,
    conformance_sha256="e" * 64,
    admission_sha256="f" * 64,
    provenance_sha256="1" * 64,
)
VALID_VERIFICATION = ContextContractReleaseVerification(
    release_pin=VALID_PIN,
    release_published=True,
    conformance_passed=True,
    admission_passed=True,
    provenance_verified=True,
)


def test_validate_context_contract_release_pin_accepts_complete_immutable_identity() -> None:
    validated = validate_context_contract_release_pin(VALID_PIN)

    assert validated == VALID_PIN
    assert validated is not VALID_PIN


@pytest.mark.parametrize(
    "release_version",
    ["main", "develop", "latest", "HEAD", "snapshot", "nightly"],
)
def test_validate_context_contract_release_pin_rejects_mutable_release_aliases(
    release_version: str,
) -> None:
    pin = replace(VALID_PIN, release_version=release_version)

    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        validate_context_contract_release_pin(pin)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("distribution_name", ""),
        ("distribution_name", "../candidate"),
        ("release_version", "0.1.0/branch"),
        ("source_commit", "A" * 40),
        ("source_commit", "abc"),
        ("distribution_sha256", "B" * 64),
        ("profile_sha256", "c" * 63),
        ("resource_sha256", None),
        ("conformance_sha256", "e" * 65),
        ("admission_sha256", True),
        ("provenance_sha256", "1" * 63),
        ("profile_name", " profile.json"),
        ("resource_name", "resource/../schema.json"),
    ],
)
def test_validate_context_contract_release_pin_rejects_malformed_identity(
    field: str,
    value: object,
) -> None:
    pin = replace(VALID_PIN, **{field: value})  # type: ignore[arg-type]

    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        validate_context_contract_release_pin(pin)


def test_validate_context_contract_release_pin_revalidates_mutated_frozen_input() -> None:
    pin = replace(VALID_PIN)
    object.__setattr__(pin, "profile_sha256", "tenant-secret")

    with pytest.raises(ContextContractReleasePinError) as raised:
        validate_context_contract_release_pin(pin)

    assert str(raised.value) == "invalid release pin"
    assert "tenant-secret" not in str(raised.value)


def test_validate_context_contract_release_pin_rejects_deleted_member() -> None:
    pin = replace(VALID_PIN)
    object.__delattr__(pin, "resource_sha256")

    with pytest.raises(ContextContractReleasePinError) as raised:
        validate_context_contract_release_pin(pin)

    assert str(raised.value) == "invalid release pin"


def test_validate_context_contract_release_pin_rejects_shaped_object_before_member_access() -> None:
    class HostilePin:
        @property
        def distribution_name(self) -> str:
            raise AssertionError("untrusted member accessed")

    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        validate_context_contract_release_pin(HostilePin())  # type: ignore[arg-type]


def test_require_context_contract_release_compatibility_accepts_exact_approved_identity() -> None:
    admitted = require_context_contract_release_compatibility(
        candidate=VALID_PIN,
        approved=replace(VALID_PIN),
    )

    assert admitted == VALID_PIN
    assert admitted is not VALID_PIN


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("release_version", "0.1.1"),
        ("source_commit", "2" * 40),
        ("distribution_sha256", "2" * 64),
        ("profile_sha256", "3" * 64),
        ("resource_sha256", "4" * 64),
        ("conformance_sha256", "5" * 64),
        ("admission_sha256", "6" * 64),
        ("provenance_sha256", "7" * 64),
    ],
)
def test_require_context_contract_release_compatibility_rejects_identity_drift(
    field: str,
    value: str,
) -> None:
    candidate = replace(VALID_PIN, **{field: value})

    with pytest.raises(ContextContractReleasePinError) as raised:
        require_context_contract_release_compatibility(
            candidate=candidate,
            approved=VALID_PIN,
        )

    assert str(raised.value) == "invalid release pin"
    assert value not in str(raised.value)


def test_require_context_contract_release_compatibility_rejects_absent_release() -> None:
    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        require_context_contract_release_compatibility(
            candidate=None,  # type: ignore[arg-type]
            approved=VALID_PIN,
        )


def test_require_context_contract_release_compatibility_revalidates_approved_policy() -> None:
    approved = replace(VALID_PIN)
    object.__setattr__(approved, "resource_sha256", "operator-secret")

    with pytest.raises(ContextContractReleasePinError) as raised:
        require_context_contract_release_compatibility(
            candidate=VALID_PIN,
            approved=approved,
        )

    assert str(raised.value) == "invalid release pin"
    assert "operator-secret" not in str(raised.value)


def test_require_context_contract_release_ready_accepts_subject_bound_verification() -> None:
    admitted = require_context_contract_release_ready(
        verification=VALID_VERIFICATION,
        approved=replace(VALID_VERIFICATION),
    )

    assert admitted == VALID_PIN
    assert admitted is not VALID_PIN


@pytest.mark.parametrize(
    "failed_gate",
    [
        "release_published",
        "conformance_passed",
        "admission_passed",
        "provenance_verified",
    ],
)
def test_require_context_contract_release_ready_rejects_missing_release_evidence(
    failed_gate: str,
) -> None:
    verification = replace(VALID_VERIFICATION, **{failed_gate: False})

    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        require_context_contract_release_ready(
            verification=verification,
            approved=VALID_VERIFICATION,
        )


@pytest.mark.parametrize("invalid_gate", [1, 0, "true", None])
def test_require_context_contract_release_ready_rejects_non_boolean_evidence(
    invalid_gate: object,
) -> None:
    verification = replace(
        VALID_VERIFICATION,
        release_published=invalid_gate,  # type: ignore[arg-type]
    )

    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        require_context_contract_release_ready(
            verification=verification,
            approved=VALID_VERIFICATION,
        )


def test_require_context_contract_release_ready_rejects_cross_release_evidence_mix() -> None:
    verification = replace(
        VALID_VERIFICATION,
        release_pin=replace(VALID_PIN, release_version="0.1.1"),
    )

    with pytest.raises(ContextContractReleasePinError) as raised:
        require_context_contract_release_ready(
            verification=verification,
            approved=VALID_VERIFICATION,
        )

    assert str(raised.value) == "invalid release pin"
    assert "0.1.1" not in str(raised.value)


def test_require_context_contract_release_ready_revalidates_mutated_verification() -> None:
    verification = replace(VALID_VERIFICATION)
    object.__setattr__(verification, "release_published", "operator-secret")

    with pytest.raises(ContextContractReleasePinError) as raised:
        require_context_contract_release_ready(
            verification=verification,
            approved=VALID_VERIFICATION,
        )

    assert str(raised.value) == "invalid release pin"
    assert "operator-secret" not in str(raised.value)


def test_require_context_contract_release_ready_revalidates_approved_verification() -> None:
    approved = replace(VALID_VERIFICATION)
    object.__setattr__(approved, "release_pin", None)

    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        require_context_contract_release_ready(
            verification=VALID_VERIFICATION,
            approved=approved,
        )


def test_require_context_contract_release_ready_rejects_deleted_verification_member() -> None:
    verification = replace(VALID_VERIFICATION)
    object.__delattr__(verification, "provenance_verified")

    with pytest.raises(ContextContractReleasePinError) as raised:
        require_context_contract_release_ready(
            verification=verification,
            approved=VALID_VERIFICATION,
        )

    assert str(raised.value) == "invalid release pin"


def test_require_context_contract_release_ready_rejects_shaped_verification_before_access() -> None:
    class HostileVerification:
        @property
        def release_pin(self) -> ContextContractReleasePin:
            raise AssertionError("untrusted verification member accessed")

    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        require_context_contract_release_ready(
            verification=HostileVerification(),  # type: ignore[arg-type]
            approved=VALID_VERIFICATION,
        )
