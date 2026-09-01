# SPDX-License-Identifier: Apache-2.0
"""Consumer contracts for immutable Context Fabric release pins."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pg_llm_batch.context_contract_release import (
    ContextContractReleasePin,
    ContextContractReleasePinError,
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


def test_validate_context_contract_release_pin_rejects_shaped_object_before_member_access() -> None:
    class HostilePin:
        @property
        def distribution_name(self) -> str:
            raise AssertionError("untrusted member accessed")

    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        validate_context_contract_release_pin(HostilePin())  # type: ignore[arg-type]
