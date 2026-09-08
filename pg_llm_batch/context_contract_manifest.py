# SPDX-License-Identifier: Apache-2.0
"""Resolve bounded local manifests into immutable Context Fabric release evidence.

The resolver accepts already-fetched bytes plus an independently supplied SHA-256
identity. It performs no network access, release discovery, credential lookup, or
policy approval. A host may therefore place its own authenticated release-discovery
boundary in front of this module without giving pg-llm-batch mutable branch or
provider authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .context_contract_release import (
    ContextContractReleasePin,
    ContextContractReleasePinError,
    ContextContractReleaseVerification,
    validate_context_contract_release_verification,
)

_MAX_RELEASE_MANIFEST_BYTES = 65_536
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_ERROR_MESSAGE = "invalid release manifest"
_MANIFEST_FIELDS = frozenset(
    {
        "distribution_name",
        "release_version",
        "source_commit",
        "distribution_sha256",
        "profile_name",
        "profile_sha256",
        "resource_name",
        "resource_sha256",
        "conformance_sha256",
        "admission_sha256",
        "provenance_sha256",
        "release_published",
        "artifact_verified",
        "conformance_passed",
        "admission_passed",
        "provenance_verified",
    }
)


class ContextContractReleaseManifestError(ValueError):
    """Report malformed or identity-mismatched release manifests without reflection."""


def _invalid_manifest() -> ContextContractReleaseManifestError:
    """Build the fixed non-reflecting error used for every manifest failure."""
    return ContextContractReleaseManifestError(_ERROR_MESSAGE)


def _validate_expected_digest(value: object) -> str:
    """Require one exact lowercase SHA-256 identity from the trusted caller."""
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        raise _invalid_manifest()
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON object keys before they can shadow release evidence."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _invalid_manifest()
        result[key] = value
    return result


def _decode_manifest(payload: bytes) -> dict[str, Any]:
    """Decode validated bounded UTF-8 JSON bytes with an exact closed field set."""
    try:
        text = payload.decode("utf-8", errors="strict")
        decoded = json.loads(text, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise _invalid_manifest() from None
    if type(decoded) is not dict or frozenset(decoded) != _MANIFEST_FIELDS:
        raise _invalid_manifest()
    return decoded


def resolve_context_contract_release_manifest(
    manifest_bytes: bytes,
    *,
    expected_manifest_sha256: str,
) -> ContextContractReleaseVerification:
    """Resolve exact manifest bytes into validated released-contract verification.

    The byte digest must be supplied independently by a trusted discovery or package
    boundary. The JSON document then has to contain exactly the package-owned
    release identity and verification fields; duplicate or unknown keys are rejected.
    Positive booleans remain observed verification only. This function never creates
    ``ContextContractReleaseApproval`` and therefore cannot authorize deployment by
    itself.

    Args:
        manifest_bytes: Exact bounded UTF-8 JSON bytes obtained by the caller.
        expected_manifest_sha256: Independently trusted SHA-256 identity for those
            exact bytes.

    Returns:
        A fresh validated verification receipt bound to one immutable release pin.

    Raises:
        ContextContractReleaseManifestError: If byte identity, JSON structure, release
            identity, or any required verification gate is invalid.
    """
    if type(manifest_bytes) is not bytes:
        raise _invalid_manifest()
    expected_digest = _validate_expected_digest(expected_manifest_sha256)
    if len(manifest_bytes) > _MAX_RELEASE_MANIFEST_BYTES or not manifest_bytes:
        raise _invalid_manifest()
    if hashlib.sha256(manifest_bytes).hexdigest() != expected_digest:
        raise _invalid_manifest()

    manifest = _decode_manifest(manifest_bytes)
    try:
        verification = ContextContractReleaseVerification(
            release_pin=ContextContractReleasePin(
                distribution_name=manifest["distribution_name"],
                release_version=manifest["release_version"],
                source_commit=manifest["source_commit"],
                distribution_sha256=manifest["distribution_sha256"],
                profile_name=manifest["profile_name"],
                profile_sha256=manifest["profile_sha256"],
                resource_name=manifest["resource_name"],
                resource_sha256=manifest["resource_sha256"],
                conformance_sha256=manifest["conformance_sha256"],
                admission_sha256=manifest["admission_sha256"],
                provenance_sha256=manifest["provenance_sha256"],
            ),
            release_published=manifest["release_published"],
            artifact_verified=manifest["artifact_verified"],
            conformance_passed=manifest["conformance_passed"],
            admission_passed=manifest["admission_passed"],
            provenance_verified=manifest["provenance_verified"],
        )
        return validate_context_contract_release_verification(verification)
    except (ContextContractReleasePinError, TypeError, KeyError):
        raise _invalid_manifest() from None
