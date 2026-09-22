# SPDX-License-Identifier: Apache-2.0
"""Classify reviewed public-contract changes against the package release policy."""

from __future__ import annotations

from enum import Enum
import re

_INVALID_CHANGE = "invalid compatibility change"
_MAX_VERSION_TEXT_LENGTH = 64
_VERSION_PATTERN = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z"
)


class CompatibilityChangeKind(Enum):
    """Supported release-compatibility classifications."""

    BACKWARD_COMPATIBLE = "backward_compatible"
    DEPRECATION = "deprecation"
    INTENTIONAL_BREAKING = "intentional_breaking"
    SECURITY_CORRECTION = "security_correction"


class CompatibilityPolicyError(ValueError):
    """Raised when release metadata violates the reviewed compatibility policy."""


def _parse_version(value: object) -> tuple[int, int, int]:
    """Parse one exact bounded canonical semantic-version authority."""
    if type(value) is not str or len(value) > _MAX_VERSION_TEXT_LENGTH:
        raise CompatibilityPolicyError(_INVALID_CHANGE)
    match = _VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise CompatibilityPolicyError(_INVALID_CHANGE)
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def classify_release_change(
    previous_version: object,
    release_version: object,
    *,
    breaks_public_contract: bool = False,
    deprecates_public_contract: bool = False,
    earliest_removal_version: object | None = None,
    security_correction: bool = False,
) -> CompatibilityChangeKind:
    """Classify one reviewed public-contract change for a candidate release."""
    if (
        type(breaks_public_contract) is not bool
        or type(deprecates_public_contract) is not bool
        or type(security_correction) is not bool
    ):
        raise CompatibilityPolicyError(_INVALID_CHANGE)

    previous = _parse_version(previous_version)
    release = _parse_version(release_version)
    if release <= previous:
        raise CompatibilityPolicyError(_INVALID_CHANGE)

    if security_correction:
        if deprecates_public_contract or earliest_removal_version is not None:
            raise CompatibilityPolicyError(_INVALID_CHANGE)
        return CompatibilityChangeKind.SECURITY_CORRECTION

    if deprecates_public_contract:
        if earliest_removal_version is None:
            raise CompatibilityPolicyError(_INVALID_CHANGE)
        removal = _parse_version(earliest_removal_version)
        if removal <= release:
            raise CompatibilityPolicyError(_INVALID_CHANGE)
        return CompatibilityChangeKind.DEPRECATION

    if earliest_removal_version is not None:
        raise CompatibilityPolicyError(_INVALID_CHANGE)

    if breaks_public_contract:
        if previous[0] == 0:
            if release[0] == 0 and release[1] <= previous[1]:
                raise CompatibilityPolicyError(_INVALID_CHANGE)
        elif release[0] <= previous[0]:
            raise CompatibilityPolicyError(_INVALID_CHANGE)
        return CompatibilityChangeKind.INTENTIONAL_BREAKING

    return CompatibilityChangeKind.BACKWARD_COMPATIBLE
