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


def test_deprecation_requires_later_removal_version() -> None:
    """A deprecation must name an earliest removal version after its release."""
    with pytest.raises(CompatibilityPolicyError, match="invalid compatibility change"):
        classify_release_change(
            "0.1.0",
            "0.1.1",
            deprecates_public_contract=True,
            earliest_removal_version="0.1.1",
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


def test_invalid_version_authority_is_rejected_without_rendering() -> None:
    """Version metadata must be exact bounded package authority, not behavior-bearing text."""
    with pytest.raises(CompatibilityPolicyError, match="invalid compatibility change"):
        classify_release_change(_HostileVersion("0.1.0"), "0.1.1")

    with pytest.raises(CompatibilityPolicyError, match="invalid compatibility change"):
        classify_release_change("0.1", "0.1.1")
