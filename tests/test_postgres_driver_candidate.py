from __future__ import annotations

import pytest

from pg_llm_batch.postgres_driver_candidate import (
    REQUIRED_POSTGRES_DRIVER_CAPABILITIES,
    REQUIRED_POSTGRES_DRIVER_PYTHON_VERSIONS,
    PostgresDriverCandidateEvidence,
    PostgresDriverCandidateEvidenceError,
    evaluate_postgres_driver_candidate,
)


FULL_CAPABILITIES = frozenset(REQUIRED_POSTGRES_DRIVER_CAPABILITIES)
FULL_PYTHON_VERSIONS = tuple(sorted(REQUIRED_POSTGRES_DRIVER_PYTHON_VERSIONS))
SOURCE_SHA = "a" * 40
ARTIFACT_SHA256 = "b" * 64
VULNERABILITY_REPORT_SHA256 = "c" * 64
LICENSE_REPORT_SHA256 = "d" * 64


def _evidence(**overrides: object) -> PostgresDriverCandidateEvidence:
    values: dict[str, object] = {
        "package_name": "candidate-driver",
        "package_version": "1.2.3",
        "license_spdx": "BSD-3-Clause",
        "python_versions": FULL_PYTHON_VERSIONS,
        "source_commit_sha": SOURCE_SHA,
        "artifact_sha256": ARTIFACT_SHA256,
        "vulnerability_report_sha256": VULNERABILITY_REPORT_SHA256,
        "known_vulnerability_ids": (),
        "capabilities": FULL_CAPABILITIES,
    }
    values.update(overrides)
    return PostgresDriverCandidateEvidence(**values)  # type: ignore[arg-type]


def test_complete_permissive_candidate_is_eligible_only_for_parity_validation() -> None:
    decision = evaluate_postgres_driver_candidate(_evidence())

    assert decision.eligible_for_parity_validation is True
    assert decision.production_approved is False
    assert decision.reasons == ()


def test_candidate_requires_immutable_license_report_identity() -> None:
    decision = evaluate_postgres_driver_candidate(
        _evidence(license_report_sha256=LICENSE_REPORT_SHA256)
    )

    assert decision.eligible_for_parity_validation is True
    assert decision.production_approved is False


@pytest.mark.parametrize(
    "license_report_sha256",
    ["d" * 63, "z" * 64, 64],
)
def test_candidate_rejects_malformed_license_report_identity(
    license_report_sha256: object,
) -> None:
    with pytest.raises(PostgresDriverCandidateEvidenceError, match="license report"):
        _evidence(license_report_sha256=license_report_sha256)


def test_candidate_contract_covers_issue_322_type_and_parameter_parity() -> None:
    assert {
        "result_row_semantics",
        "sql_parameter_style_adaptation",
        "uuid_timestamp_adaptation",
    } <= REQUIRED_POSTGRES_DRIVER_CAPABILITIES


def test_candidate_contract_preserves_each_supported_dsn_selector_family() -> None:
    assert {
        "conninfo_keyword_parse_render",
        "conninfo_service_selector",
        "conninfo_uri_parse_render",
    } <= REQUIRED_POSTGRES_DRIVER_CAPABILITIES


def test_candidate_contract_requires_every_repository_ci_python_version() -> None:
    assert REQUIRED_POSTGRES_DRIVER_PYTHON_VERSIONS == frozenset(
        {"3.10", "3.11", "3.12", "3.13", "3.14"}
    )


def test_candidate_rejects_known_vulnerabilities_before_parity_validation() -> None:
    decision = evaluate_postgres_driver_candidate(
        _evidence(known_vulnerability_ids=("CVE-2025-61385",))
    )

    assert decision.eligible_for_parity_validation is False
    assert decision.production_approved is False
    assert decision.reasons == ("known_vulnerability:CVE-2025-61385",)


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


@pytest.mark.parametrize(
    "missing_version", ["3.10", "3.11", "3.12", "3.13", "3.14"]
)
def test_candidate_requires_every_repository_ci_python_version(
    missing_version: str,
) -> None:
    candidate_versions = tuple(
        version for version in FULL_PYTHON_VERSIONS if version != missing_version
    )
    decision = evaluate_postgres_driver_candidate(
        _evidence(python_versions=candidate_versions)
    )

    assert decision.eligible_for_parity_validation is False
    assert decision.reasons == (f"missing_python_version:{missing_version}",)


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
        ("package_name", 7),
        ("package_version", ""),
        ("package_version", False),
        ("license_spdx", ""),
        ("license_spdx", object()),
        ("python_versions", ()),
        ("python_versions", ["3.14"]),
        ("source_commit_sha", "a" * 39),
        ("source_commit_sha", "g" * 40),
        ("source_commit_sha", 40),
        ("artifact_sha256", "b" * 63),
        ("artifact_sha256", "z" * 64),
        ("artifact_sha256", 64),
        ("vulnerability_report_sha256", "c" * 63),
        ("vulnerability_report_sha256", "z" * 64),
        ("vulnerability_report_sha256", 64),
        ("known_vulnerability_ids", ["CVE-2025-61385"]),
        ("capabilities", frozenset()),
        ("capabilities", {"parameterized_sql"}),
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


def test_candidate_rejects_non_string_python_version_tokens() -> None:
    with pytest.raises(PostgresDriverCandidateEvidenceError, match="Python version"):
        _evidence(python_versions=("3.14", 314))


def test_candidate_rejects_unknown_capability_names() -> None:
    with pytest.raises(PostgresDriverCandidateEvidenceError, match="capability"):
        _evidence(capabilities=FULL_CAPABILITIES | {"model_routing"})


@pytest.mark.parametrize(
    "vulnerability_id",
    [
        "",
        "CVE 2025 61385",
        "CVE-2025-61385\nGHSA-wq2g-r956-j8cc",
        "x" * 129,
    ],
)
def test_candidate_rejects_malformed_vulnerability_identifiers(
    vulnerability_id: str,
) -> None:
    with pytest.raises(PostgresDriverCandidateEvidenceError, match="vulnerability"):
        _evidence(known_vulnerability_ids=(vulnerability_id,))


def test_candidate_rejects_duplicate_vulnerability_identifiers() -> None:
    with pytest.raises(PostgresDriverCandidateEvidenceError, match="vulnerability"):
        _evidence(
            known_vulnerability_ids=("CVE-2025-61385", "CVE-2025-61385")
        )


def test_candidate_rejects_unbounded_python_version_evidence() -> None:
    versions = FULL_PYTHON_VERSIONS + tuple(f"4.{minor}" for minor in range(28))

    with pytest.raises(PostgresDriverCandidateEvidenceError, match="Python version"):
        _evidence(python_versions=versions)


def test_candidate_rejects_unbounded_vulnerability_evidence() -> None:
    vulnerability_ids = tuple(f"CVE-2099-{index:04d}" for index in range(257))

    with pytest.raises(PostgresDriverCandidateEvidenceError, match="vulnerability"):
        _evidence(known_vulnerability_ids=vulnerability_ids)


@pytest.mark.parametrize(
    ("field_name", "mutated_value"),
    [
        ("python_versions", ["3.14"]),
        ("known_vulnerability_ids", ["CVE-2025-61385"]),
        ("capabilities", set(FULL_CAPABILITIES)),
    ],
)
def test_candidate_evaluation_revalidates_post_construction_container_mutation(
    field_name: str,
    mutated_value: object,
) -> None:
    evidence = _evidence()
    object.__setattr__(evidence, field_name, mutated_value)

    with pytest.raises(PostgresDriverCandidateEvidenceError):
        evaluate_postgres_driver_candidate(evidence)


def test_candidate_evaluation_normalizes_deleted_authority_field() -> None:
    evidence = _evidence()
    object.__delattr__(evidence, "capabilities")

    with pytest.raises(PostgresDriverCandidateEvidenceError):
        evaluate_postgres_driver_candidate(evidence)


def test_candidate_evaluation_rejects_shaped_object_before_member_access() -> None:
    class CandidateShapedObject:
        @property
        def license_spdx(self) -> str:
            raise AssertionError("candidate-shaped object member was evaluated")

    with pytest.raises(PostgresDriverCandidateEvidenceError):
        evaluate_postgres_driver_candidate(CandidateShapedObject())  # type: ignore[arg-type]


@pytest.mark.parametrize("field_name", ["package_name", "package_version", "license_spdx"])
def test_candidate_rejects_surrounding_whitespace_in_identity_evidence(
    field_name: str,
) -> None:
    with pytest.raises(PostgresDriverCandidateEvidenceError):
        _evidence(**{field_name: " candidate-driver "})


@pytest.mark.parametrize(
    "identity_value",
    [
        "candidate\ndriver",
        "candidate\tdriver",
        "candidate\u00a0driver",
        "candidate\x7fdriver",
    ],
)
def test_candidate_rejects_embedded_whitespace_or_control_identity_evidence(
    identity_value: str,
) -> None:
    with pytest.raises(PostgresDriverCandidateEvidenceError):
        _evidence(package_name=identity_value)


@pytest.mark.parametrize(
    "identity_value",
    [
        "candidate\u200bdriver",
        "candidate\u202edriver",
        "candidate\u2066driver",
    ],
)
def test_candidate_rejects_unicode_format_controls_in_identity_evidence(
    identity_value: str,
) -> None:
    with pytest.raises(PostgresDriverCandidateEvidenceError):
        _evidence(package_name=identity_value)


@pytest.mark.parametrize("field_name", ["package_name", "package_version", "license_spdx"])
def test_candidate_rejects_unbounded_identity_evidence(field_name: str) -> None:
    with pytest.raises(PostgresDriverCandidateEvidenceError):
        _evidence(**{field_name: "x" * 257})


def test_candidate_rejects_duplicate_python_version_evidence() -> None:
    with pytest.raises(PostgresDriverCandidateEvidenceError, match="Python version"):
        _evidence(python_versions=("3.14", "3.14"))
