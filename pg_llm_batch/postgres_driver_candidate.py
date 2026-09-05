"""Fail-closed commercial acceptance for PostgreSQL driver candidates.

The repository must replace its current LGPL-family Psycopg runtime dependency
without turning an unverified alternative into production authority. This module
revalidates a bounded candidate snapshot and decides only whether a candidate
has enough permissive-license, immutable license/artifact identity, Python-version,
vulnerability, and capability evidence to enter parity validation. Production
approval remains a later gate that requires a concrete adapter plus
PostgreSQL/RLS/recovery/package evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


REQUIRED_POSTGRES_DRIVER_CAPABILITIES = frozenset(
    {
        "autocommit_state",
        "connection_closed_state",
        "connection_context",
        "connection_context_commit_rollback",
        "connection_thread_affinity",
        "conninfo_keyword_parse_render",
        "conninfo_service_selector",
        "conninfo_uri_parse_render",
        "cursor_context",
        "finite_connect_timeout",
        "invalid_conninfo_classification",
        "jsonb",
        "parameterized_sql",
        "result_row_semantics",
        "row_count",
        "sql_parameter_style_adaptation",
        "transaction_commit_rollback",
        "undefined_function_classification",
        "uuid_timestamp_adaptation",
    }
)
"""Capabilities a replacement driver must evidence before parity validation."""

REQUIRED_POSTGRES_DRIVER_PYTHON_VERSIONS = frozenset(
    {"3.10", "3.11", "3.12", "3.13", "3.14"}
)
"""Repository-supported Python minors a replacement driver must evidence explicitly."""

POSTGRES_DRIVER_CANDIDATE_EVIDENCE_SCHEMA_VERSION = "2"
"""Version of the candidate-evidence receipt interpreted by this evaluator."""

_APPROVED_PERMISSIVE_LICENSES = frozenset(
    {
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "MIT",
        "PostgreSQL",
    }
)
_MAX_IDENTITY_EVIDENCE_BYTES = 256
_MAX_PYTHON_VERSION_EVIDENCE_ITEMS = 32
_MAX_VULNERABILITY_EVIDENCE_ITEMS = 256
_MINOR_PYTHON_VERSION = re.compile(r"^[1-9][0-9]*\.[0-9]+$")
_PYPA_DISTRIBUTION_NAME = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\Z"
)
_SOURCE_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_ARTIFACT_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VULNERABILITY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class PostgresDriverCandidateEvidenceError(ValueError):
    """Reject malformed or mutable evidence before commercial evaluation.

    Candidate metadata can influence a supply-chain migration decision, so the
    evaluator accepts only immutable primitive evidence with exact digest and
    version shapes. It never repairs or guesses malformed package metadata.
    """


def _validate_identity_text(label: str, value: object) -> None:
    """Require one finite, exact package-identity token without normalization.

    Package name, version, and SPDX evidence participate in an acquisition
    decision and can arrive from untrusted package metadata. Rejecting whitespace,
    controls, malformed Unicode, and Unicode format characters keeps one evidence
    value from becoming multiple visual or line-oriented identities, while the
    UTF-8 byte ceiling bounds malformed metadata without inventing a
    package-manager-specific grammar.
    """
    if type(value) is not str or not value:
        raise PostgresDriverCandidateEvidenceError(
            f"PostgreSQL driver {label} evidence is invalid"
        )
    try:
        encoded_value = value.encode("utf-8")
    except UnicodeEncodeError:
        raise PostgresDriverCandidateEvidenceError(
            f"PostgreSQL driver {label} evidence is invalid"
        ) from None
    if (
        len(encoded_value) > _MAX_IDENTITY_EVIDENCE_BYTES
        or any(
            character.isspace()
            or ord(character) < 32
            or ord(character) == 127
            or unicodedata.category(character) == "Cf"
            for character in value
        )
    ):
        raise PostgresDriverCandidateEvidenceError(
            f"PostgreSQL driver {label} evidence is invalid"
        )


def _validate_vulnerability_ids(values: object) -> tuple[str, ...]:
    """Validate bounded advisory identifiers without normalizing scan evidence.

    The tuple may be empty only when the bound vulnerability report found no
    known advisories. Identifiers remain opaque CVE/GHSA/vendor tokens; the
    evaluator constrains their representation and cardinality rather than
    inventing a namespace or letting untrusted scan metadata amplify evaluation
    work and decision receipts without bound.
    """
    if (
        type(values) is not tuple
        or len(values) > _MAX_VULNERABILITY_EVIDENCE_ITEMS
    ):
        raise PostgresDriverCandidateEvidenceError(
            "PostgreSQL driver vulnerability evidence is invalid"
        )
    if any(
        type(value) is not str or _VULNERABILITY_ID.fullmatch(value) is None
        for value in values
    ):
        raise PostgresDriverCandidateEvidenceError(
            "PostgreSQL driver vulnerability evidence is invalid"
        )
    if len(set(values)) != len(values):
        raise PostgresDriverCandidateEvidenceError(
            "PostgreSQL driver vulnerability evidence is invalid"
        )
    return values


@dataclass(frozen=True, slots=True)
class PostgresDriverCandidateEvidence:
    """Describe one validated PostgreSQL-driver package candidate.

    ``source_commit_sha`` identifies the reviewed source revision,
    ``license_report_sha256`` binds the exact license evidence used for
    ``license_spdx``, ``artifact_sha256`` identifies the exact distributable,
    ``vulnerability_report_sha256`` binds the exact vulnerability evidence used
    for the decision, and ``capability_report_sha256`` binds the exact parity
    capability report from which ``capabilities`` is derived.
    ``known_vulnerability_ids`` records unresolved advisories from the bound
    vulnerability report. ``python_versions`` and ``capabilities`` must contain
    explicit evidence rather than inferred support from a nearby release or
    similar database driver. ``evidence_schema_version`` prevents a future
    receipt shape from being silently interpreted under today's semantics.
    Evaluation revalidates a fresh snapshot because Python's frozen dataclasses
    do not make ``object.__setattr__`` an authority boundary.
    """

    package_name: str
    package_version: str
    license_spdx: str
    license_report_sha256: str
    python_versions: tuple[str, ...]
    source_commit_sha: str
    artifact_sha256: str
    vulnerability_report_sha256: str
    capability_report_sha256: str
    known_vulnerability_ids: tuple[str, ...]
    capabilities: frozenset[str]
    evidence_schema_version: str = POSTGRES_DRIVER_CANDIDATE_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Validate candidate evidence without normalizing ambiguous inputs."""
        for label, value in (
            ("package name", self.package_name),
            ("package version", self.package_version),
            ("license", self.license_spdx),
        ):
            _validate_identity_text(label, value)
        if _PYPA_DISTRIBUTION_NAME.fullmatch(self.package_name) is None:
            raise PostgresDriverCandidateEvidenceError(
                "PostgreSQL driver package name evidence is invalid"
            )
        if (
            type(self.evidence_schema_version) is not str
            or self.evidence_schema_version
            != POSTGRES_DRIVER_CANDIDATE_EVIDENCE_SCHEMA_VERSION
        ):
            raise PostgresDriverCandidateEvidenceError(
                "PostgreSQL driver candidate evidence schema version is unsupported"
            )
        if (
            type(self.license_report_sha256) is not str
            or _ARTIFACT_SHA256.fullmatch(self.license_report_sha256) is None
        ):
            raise PostgresDriverCandidateEvidenceError(
                "PostgreSQL driver license report evidence is invalid"
            )
        if (
            type(self.python_versions) is not tuple
            or not self.python_versions
            or len(self.python_versions) > _MAX_PYTHON_VERSION_EVIDENCE_ITEMS
        ):
            raise PostgresDriverCandidateEvidenceError(
                "PostgreSQL driver Python version evidence is invalid"
            )
        if any(
            type(version) is not str or _MINOR_PYTHON_VERSION.fullmatch(version) is None
            for version in self.python_versions
        ):
            raise PostgresDriverCandidateEvidenceError(
                "PostgreSQL driver Python version evidence is invalid"
            )
        if len(set(self.python_versions)) != len(self.python_versions):
            raise PostgresDriverCandidateEvidenceError(
                "PostgreSQL driver Python version evidence is invalid"
            )
        if (
            type(self.source_commit_sha) is not str
            or _SOURCE_COMMIT_SHA.fullmatch(self.source_commit_sha) is None
        ):
            raise PostgresDriverCandidateEvidenceError(
                "PostgreSQL driver source commit evidence is invalid"
            )
        if (
            type(self.artifact_sha256) is not str
            or _ARTIFACT_SHA256.fullmatch(self.artifact_sha256) is None
        ):
            raise PostgresDriverCandidateEvidenceError(
                "PostgreSQL driver artifact digest evidence is invalid"
            )
        if (
            type(self.vulnerability_report_sha256) is not str
            or _ARTIFACT_SHA256.fullmatch(self.vulnerability_report_sha256) is None
        ):
            raise PostgresDriverCandidateEvidenceError(
                "PostgreSQL driver vulnerability report evidence is invalid"
            )
        if (
            type(self.capability_report_sha256) is not str
            or _ARTIFACT_SHA256.fullmatch(self.capability_report_sha256) is None
        ):
            raise PostgresDriverCandidateEvidenceError(
                "PostgreSQL driver capability report evidence is invalid"
            )
        _validate_vulnerability_ids(self.known_vulnerability_ids)
        if type(self.capabilities) is not frozenset or not self.capabilities:
            raise PostgresDriverCandidateEvidenceError(
                "PostgreSQL driver capability evidence is invalid"
            )
        if any(type(capability) is not str for capability in self.capabilities):
            raise PostgresDriverCandidateEvidenceError(
                "PostgreSQL driver capability evidence is invalid"
            )
        if len(self.capabilities) > len(REQUIRED_POSTGRES_DRIVER_CAPABILITIES):
            raise PostgresDriverCandidateEvidenceError(
                "PostgreSQL driver capability evidence contains an unknown capability"
            )
        unknown_capabilities = self.capabilities - REQUIRED_POSTGRES_DRIVER_CAPABILITIES
        if unknown_capabilities:
            raise PostgresDriverCandidateEvidenceError(
                "PostgreSQL driver capability evidence contains an unknown capability"
            )


@dataclass(frozen=True, slots=True)
class PostgresDriverCandidateDecision:
    """Record whether validated evidence permits candidate parity validation.

    ``production_approved`` is deliberately always false in this stage. A package
    that clears this evaluator still needs a concrete ``PostgresDriverPort``
    adapter and realistic PostgreSQL/RLS/concurrency/recovery/package gates.
    """

    eligible_for_parity_validation: bool
    production_approved: bool
    reasons: tuple[str, ...]


def _validated_candidate_snapshot(
    evidence: PostgresDriverCandidateEvidence,
) -> PostgresDriverCandidateEvidence:
    """Capture and revalidate exact package evidence before policy evaluation.

    Candidate evidence crosses a supply-chain decision boundary. Requiring the
    exact package type before member access prevents candidate-shaped objects from
    executing caller-controlled accessors, while reconstruction reapplies every
    primitive/container invariant after any post-construction mutation. Deleted
    slots are normalized to the package's fixed evidence error.
    """
    if type(evidence) is not PostgresDriverCandidateEvidence:
        raise PostgresDriverCandidateEvidenceError(
            "PostgreSQL driver candidate evidence is invalid"
        )
    try:
        return PostgresDriverCandidateEvidence(
            package_name=evidence.package_name,
            package_version=evidence.package_version,
            license_spdx=evidence.license_spdx,
            license_report_sha256=evidence.license_report_sha256,
            python_versions=evidence.python_versions,
            source_commit_sha=evidence.source_commit_sha,
            artifact_sha256=evidence.artifact_sha256,
            vulnerability_report_sha256=evidence.vulnerability_report_sha256,
            capability_report_sha256=evidence.capability_report_sha256,
            known_vulnerability_ids=evidence.known_vulnerability_ids,
            capabilities=evidence.capabilities,
            evidence_schema_version=evidence.evidence_schema_version,
        )
    except AttributeError:
        raise PostgresDriverCandidateEvidenceError(
            "PostgreSQL driver candidate evidence is invalid"
        ) from None


def evaluate_postgres_driver_candidate(
    evidence: PostgresDriverCandidateEvidence,
) -> PostgresDriverCandidateDecision:
    """Evaluate one candidate without promoting it to a production dependency.

    The decision first revalidates one exact package-owned snapshot, then fails
    closed when the bound vulnerability report contains a known advisory, the
    SPDX identifier is not in the repository's explicitly reviewed permissive
    set, any repository-required Python runtime is not evidenced, or any runtime
    capability required by the migration port is absent. DSN evidence remains
    split across URI, keyword, and service selectors so a driver cannot claim
    generic conninfo support while silently dropping a shipped selector family.
    Reasons are deterministic so CI and acquisition diligence can compare exact
    evidence.
    """
    snapshot = _validated_candidate_snapshot(evidence)
    reasons = [
        f"known_vulnerability:{vulnerability_id}"
        for vulnerability_id in sorted(snapshot.known_vulnerability_ids)
    ]
    if snapshot.license_spdx not in _APPROVED_PERMISSIVE_LICENSES:
        reasons.append("license_not_approved")
    missing_python_versions = REQUIRED_POSTGRES_DRIVER_PYTHON_VERSIONS - set(
        snapshot.python_versions
    )
    reasons.extend(
        f"missing_python_version:{version}"
        for version in sorted(missing_python_versions)
    )
    missing_capabilities = REQUIRED_POSTGRES_DRIVER_CAPABILITIES - snapshot.capabilities
    reasons.extend(
        f"missing_capability:{capability}"
        for capability in sorted(missing_capabilities)
    )
    return PostgresDriverCandidateDecision(
        eligible_for_parity_validation=not reasons,
        production_approved=False,
        reasons=tuple(reasons),
    )
