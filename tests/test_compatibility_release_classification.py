# SPDX-License-Identifier: Apache-2.0
"""Release compatibility classification must be deterministic and fail closed."""

from __future__ import annotations

import pytest

from pg_llm_batch.compatibility_change import (
    CompatibilityChangeKind,
    CompatibilityPolicyError,
    classify_release_change,
)


class _HostileVersion(str):
    """Version-shaped caller authority that must not execute custom protocols."""

    def __str__(self) -> str:
        raise AssertionError("caller-controlled __str__ executed")

    def __repr__(self) -> str:
        raise AssertionError("caller-controlled __repr__ executed")


class _HostileFlag:
    """Boolean-shaped caller authority that must not execute custom protocols."""

    def __bool__(self) -> bool:
        raise AssertionError("caller-controlled __bool__ executed")

    def __str__(self) -> str:
        raise AssertionError("caller-controlled __str__ executed")

    def __repr__(self) -> str:
        raise AssertionError("caller-controlled __repr__ executed")


def test_backward_compatible_patch_is_classified() -> None:
    """A pre-1.0 patch without a breaking marker remains backward compatible."""
    assert (
        classify_release_change("0.1.0", "0.1.1")
        is CompatibilityChangeKind.BACKWARD_COMPATIBLE
    )


def test_pre_one_breaking_patch_fails_closed() -> None:
    """A planned pre-1.0 breaking change must not first ship as a patch."""
    with pytest.raises(CompatibilityPolicyError, match="invalid compatibility change"):
        classify_release_change(
            "0.1.0",
            "0.1.1",
            breaks_public_contract=True,
        )


def test_pre_one_breaking_minor_is_classified() -> None:
    """A deliberate pre-1.0 breaking change may be classified on a later minor."""
    assert (
        classify_release_change(
            "0.1.0",
            "0.2.0",
            breaks_public_contract=True,
        )
        is CompatibilityChangeKind.INTENTIONAL_BREAKING
    )
    assert (
        classify_release_change(
            "0.9.0",
            "1.0.0",
            breaks_public_contract=True,
        )
        is CompatibilityChangeKind.INTENTIONAL_BREAKING
    )


def test_deprecation_requires_later_removal_version() -> None:
    """A deprecation must name an earliest removal version after its release."""
    with pytest.raises(CompatibilityPolicyError, match="invalid compatibility change"):
        classify_release_change(
            "0.1.0",
            "0.1.1",
            deprecates_public_contract=True,
            earliest_removal_version="0.1.1",
        )

    with pytest.raises(CompatibilityPolicyError, match="invalid compatibility change"):
        classify_release_change(
            "0.1.0",
            "0.1.1",
            deprecates_public_contract=True,
        )

    assert (
        classify_release_change(
            "0.1.0",
            "0.1.1",
            deprecates_public_contract=True,
            earliest_removal_version="0.2.0",
        )
        is CompatibilityChangeKind.DEPRECATION
    )


def test_security_correction_can_override_patch_compatibility() -> None:
    """A fail-closed security correction is distinct from ordinary breaking change."""
    assert (
        classify_release_change(
            "0.1.0",
            "0.1.1",
            breaks_public_contract=True,
            security_correction=True,
        )
        is CompatibilityChangeKind.SECURITY_CORRECTION
    )


def test_security_correction_rejects_deprecation_metadata() -> None:
    """Security classification must not bypass malformed deprecation metadata."""
    with pytest.raises(CompatibilityPolicyError, match="invalid compatibility change"):
        classify_release_change(
            "0.1.0",
            "0.1.1",
            deprecates_public_contract=True,
            security_correction=True,
        )

    with pytest.raises(CompatibilityPolicyError, match="invalid compatibility change"):
        classify_release_change(
            "0.1.0",
            "0.1.1",
            earliest_removal_version="0.2.0",
            security_correction=True,
        )


def test_change_flags_require_exact_boolean_authority() -> None:
    """Classification flags must be exact booleans rather than truthy caller authority."""
    invalid_cases = (
        {"breaks_public_contract": 1},
        {
            "deprecates_public_contract": 1,
            "earliest_removal_version": "0.2.0",
        },
        {"security_correction": 1},
        {"breaks_public_contract": _HostileFlag()},
        {
            "deprecates_public_contract": _HostileFlag(),
            "earliest_removal_version": "0.2.0",
        },
        {"security_correction": _HostileFlag()},
    )
    for metadata in invalid_cases:
        with pytest.raises(CompatibilityPolicyError, match="invalid compatibility change"):
            classify_release_change("0.1.0", "0.2.0", **metadata)


def test_invalid_version_authority_is_rejected_without_rendering() -> None:
    """Version metadata must be exact bounded package authority, not behavior-bearing text."""
    with pytest.raises(CompatibilityPolicyError, match="invalid compatibility change"):
        classify_release_change(_HostileVersion("0.1.0"), "0.1.1")

    with pytest.raises(CompatibilityPolicyError, match="invalid compatibility change"):
        classify_release_change("0.1", "0.1.1")

    with pytest.raises(CompatibilityPolicyError, match="invalid compatibility change"):
        classify_release_change("1" * 65, "0.1.1")


def test_release_order_and_orphan_removal_metadata_fail_closed() -> None:
    """Release order and removal metadata must remain internally consistent."""
    with pytest.raises(CompatibilityPolicyError, match="invalid compatibility change"):
        classify_release_change("0.1.0", "0.1.0")

    with pytest.raises(CompatibilityPolicyError, match="invalid compatibility change"):
        classify_release_change(
            "0.1.0",
            "0.1.1",
            earliest_removal_version="0.2.0",
        )


def test_stable_breaking_change_requires_major_release() -> None:
    """After 1.0 an intentional breaking change requires a later major version."""
    with pytest.raises(CompatibilityPolicyError, match="invalid compatibility change"):
        classify_release_change(
            "1.2.0",
            "1.3.0",
            breaks_public_contract=True,
        )

    assert (
        classify_release_change(
            "1.2.0",
            "2.0.0",
            breaks_public_contract=True,
        )
        is CompatibilityChangeKind.INTENTIONAL_BREAKING
    )
