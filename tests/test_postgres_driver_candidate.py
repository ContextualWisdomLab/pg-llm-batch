from __future__ import annotations

import pytest

from pg_llm_batch.postgres_driver_candidate import (
    REQUIRED_POSTGRES_DRIVER_CAPABILITIES,
    PostgresDriverCandidateEvidence,
    PostgresDriverCandidateEvidenceError,
    evaluate_postgres_driver_candidate,
)


FULL_CAPABILITIES = frozenset(REQUIRED_POSTGRES_DRIVER_CAPABILITIES)
SOURCE_SHA = "a" * 40
ARTIFACT_SHA256 = "b" * 64


def _evidence(**overrides: object) -> PostgresDriverCandidateEvidence:
    values: dict[str, object] = {
        "package_name": "candidate-driver",
        "package_version": "1.2.3",
        "license_spdx": "BSD-3-Clause",
        "python_versions": ("3.12", "3.13", "3.14"),
        "source_commit_sha": SOURCE_SHA,
        "artifact_sha256": ARTIFACT_SHA256,
        "capabilities": FULL_CAPABILITIES,
    }
    values.update(overrides)
    return PostgresDriverCandidateEvidence(**values)  # type: ignore[arg-type]


def test_complete_permissive_candidate_is_eligible_only_for_parity_validation() -> None:
    decision = evaluate_postgres_driver_candidate(_evidence())

    assert decision.eligible_for_parity_validation is True
    assert decision.production_approved is False
    assert decision.reasons == ()


@pytest.mark.parametrize(
    ("license_spdx", "expected_reason"),
    [
        ("LGPL-3.0-only", "license_not_approved"),
        ("GPL-3.0-only", "license_not_approved"),
        ("AGPL-3.0-only", "license_not_approved"),
        ("LicenseRef-Proprietary", "license_not_approved"),
    ],
)
def test_candidate_fails_closed_when_license_is_not_explicitly_permissive(
    license_spdx: str,
    expected_reason: str,
) -> None:
    decision = evaluate_postgres_driver_candidate(_evidence(license_spdx=license_spdx))

    assert decision.eligible_for_parity_validation is False
    assert decision.production_approved is False
    assert expected_reason in decision.reasons


def test_candidate_requires_explicit_python_314_support_evidence() -> None:
    decision = evaluate_postgres_driver_candidate(
        _evidence(python_versions=("3.12", "3.13"))
    )

    assert decision.eligible_for_parity_validation is False
    assert decision.reasons == ("python_3_14_not_evidenced",)


def test_candidate_reports_every_missing_runtime_capability_deterministically() -> None:
    decision = evaluate_postgres_driver_candidate(
        _evidence(capabilities=frozenset({"parameterized_sql", "jsonb"}))
    )

    expected_missing = sorted(
        FULL_CAPABILITIES - {"parameterized_sql", "jsonb"}
    )
    assert decision.eligible_for_parity_validation is False
    assert decision.reasons == tuple(
        f"missing_capability:{capability}" for capability in expected_missing
    )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("package_name", ""),
        ("package_version", ""),
        ("license_spdx", ""),
        ("python_versions", ()),
        ("source_commit_sha", "a" * 39),
        ("source_commit_sha", "g" * 40),
        ("artifact_sha256", "b" * 63),
        ("artifact_sha256", "z" * 64),
        ("capabilities", frozenset()),
    ],
)
def test_candidate_rejects_incomplete_or_nonimmutable_evidence(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(PostgresDriverCandidateEvidenceError):
        _evidence(**{field_name: value})


def test_candidate_rejects_ambiguous_python_version_tokens() -> None:
    with pytest.raises(PostgresDriverCandidateEvidenceError, match="Python version"):
        _evidence(python_versions=("3.14+",))


def test_candidate_rejects_unknown_capability_names() -> None:
    with pytest.raises(PostgresDriverCandidateEvidenceError, match="capability"):
        _evidence(capabilities=FULL_CAPABILITIES | {"model_routing"})
