# SPDX-License-Identifier: Apache-2.0
"""Regression tests for bounded immutable Context Fabric release manifests."""

from __future__ import annotations

import hashlib
import json

import pytest

from pg_llm_batch.context_contract_manifest import (
    ContextContractReleaseManifestError,
    resolve_context_contract_release_manifest,
)
from pg_llm_batch.context_contract_release import ContextContractReleaseVerification


_HEX_A = "a" * 64
_HEX_B = "b" * 64
_HEX_C = "c" * 64
_HEX_D = "d" * 64
_HEX_E = "e" * 64
_HEX_F = "f" * 64
_HEX_1 = "1" * 64


def _manifest() -> dict[str, object]:
    """Return one valid content-free released-contract manifest fixture."""
    return {
        "distribution_name": "context-graph-contracts",
        "release_version": "1.0.0",
        "source_commit": "1" * 40,
        "distribution_sha256": _HEX_A,
        "profile_name": "context-assertion-v1",
        "profile_sha256": _HEX_B,
        "resource_name": "context-assertion.schema.json",
        "resource_sha256": _HEX_C,
        "conformance_sha256": _HEX_D,
        "admission_sha256": _HEX_E,
        "provenance_sha256": _HEX_F,
        "release_published": True,
        "artifact_verified": True,
        "conformance_passed": True,
        "admission_passed": True,
        "provenance_verified": True,
    }


def _encoded(manifest: dict[str, object]) -> bytes:
    """Encode one deterministic UTF-8 manifest fixture."""
    return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(payload: bytes) -> str:
    """Return the exact SHA-256 identity expected by the resolver."""
    return hashlib.sha256(payload).hexdigest()


def test_release_manifest_resolver_binds_exact_bytes_and_release_gates() -> None:
    """A verified manifest resolves to one subject-bound release verification."""
    payload = _encoded(_manifest())

    resolved = resolve_context_contract_release_manifest(
        payload,
        expected_manifest_sha256=_digest(payload),
    )

    assert type(resolved) is ContextContractReleaseVerification
    assert resolved.release_pin.distribution_name == "context-graph-contracts"
    assert resolved.release_pin.release_version == "1.0.0"
    assert resolved.release_pin.source_commit == "1" * 40
    assert resolved.release_published is True
    assert resolved.artifact_verified is True
    assert resolved.conformance_passed is True
    assert resolved.admission_passed is True
    assert resolved.provenance_verified is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: (payload, _HEX_1),
        lambda payload: (payload + b" ", _digest(payload)),
        lambda payload: (b"\xff", _digest(b"\xff")),
        lambda payload: (b"[1,2,3]", _digest(b"[1,2,3]")),
    ],
)
def test_release_manifest_resolver_rejects_untrusted_byte_identity(
    mutation,
) -> None:
    """Digest drift, malformed UTF-8, or a non-object manifest fails closed."""
    payload = _encoded(_manifest())
    candidate, expected = mutation(payload)

    with pytest.raises(ContextContractReleaseManifestError, match="^invalid release manifest$"):
        resolve_context_contract_release_manifest(
            candidate,
            expected_manifest_sha256=expected,
        )


def test_release_manifest_resolver_rejects_duplicate_or_unknown_fields() -> None:
    """Ambiguous duplicate keys and schema expansion cannot enter release authority."""
    manifest = _manifest()
    payload = _encoded({**manifest, "unexpected": "value"})
    with pytest.raises(ContextContractReleaseManifestError, match="^invalid release manifest$"):
        resolve_context_contract_release_manifest(
            payload,
            expected_manifest_sha256=_digest(payload),
        )

    duplicate = (
        b'{"distribution_name":"context-graph-contracts",'
        b'"distribution_name":"other"}'
    )
    with pytest.raises(ContextContractReleaseManifestError, match="^invalid release manifest$"):
        resolve_context_contract_release_manifest(
            duplicate,
            expected_manifest_sha256=_digest(duplicate),
        )


def test_release_manifest_resolver_rejects_false_gate_and_oversize_input() -> None:
    """Caller-declared incomplete verification and unbounded manifests fail closed."""
    manifest = _manifest()
    manifest["provenance_verified"] = False
    payload = _encoded(manifest)
    with pytest.raises(ContextContractReleaseManifestError, match="^invalid release manifest$"):
        resolve_context_contract_release_manifest(
            payload,
            expected_manifest_sha256=_digest(payload),
        )

    oversized = b"{" + b" " * 65536 + b"}"
    with pytest.raises(ContextContractReleaseManifestError, match="^invalid release manifest$"):
        resolve_context_contract_release_manifest(
            oversized,
            expected_manifest_sha256=_digest(oversized),
        )


def test_release_manifest_resolver_requires_exact_bytes_and_digest_types() -> None:
    """Shaped byte containers and digest values cannot execute or coerce at admission."""
    payload = _encoded(_manifest())

    with pytest.raises(ContextContractReleaseManifestError, match="^invalid release manifest$"):
        resolve_context_contract_release_manifest(
            bytearray(payload),  # type: ignore[arg-type]
            expected_manifest_sha256=_digest(payload),
        )
    with pytest.raises(ContextContractReleaseManifestError, match="^invalid release manifest$"):
        resolve_context_contract_release_manifest(
            payload,
            expected_manifest_sha256=object(),  # type: ignore[arg-type]
        )


def test_release_manifest_resolver_contains_recursive_json_failure() -> None:
    """Parser recursion exhaustion is contained behind the fixed admission error."""
    nested = b'{' + b'"distribution_name":' + (b"[" * 1100) + b"0" + (b"]" * 1100) + b"}"

    with pytest.raises(ContextContractReleaseManifestError, match="^invalid release manifest$"):
        resolve_context_contract_release_manifest(
            nested,
            expected_manifest_sha256=_digest(nested),
        )
