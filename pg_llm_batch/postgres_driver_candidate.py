"""Fail-closed commercial acceptance for PostgreSQL driver candidates.

The repository must replace its current LGPL-family Psycopg runtime dependency
without turning an unverified alternative into production authority. This module
revalidates a bounded candidate snapshot and decides only whether a candidate
has enough permissive-license, Python-version, artifact-identity, and capability
evidence to enter parity validation. Production approval remains a later gate
that requires a concrete adapter plus PostgreSQL/RLS/recovery/package evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


REQUIRED_POSTGRES_DRIVER_CAPABILITIES = frozenset(
    {
        "autocommit_state",
        "connection_closed_state",
        "connection_context",
        "conninfo_parse_render",
        "cursor_context",
        "finite_connect_timeout",
        "jsonb",
        "parameterized_sql",
        "row_count",
        "transaction_commit_rollback",
        "undefined_function_classification",
    }
)
"""Capabilities a replacement driver must evidence before parity validation."""

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
_MINOR_PYTHON_VERSION = re.compile(r"^[1-9][0-9]*\.[0-9]+$")
_SOURCE_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_ARTIFACT_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PostgresDriverCandidateEvidenceError(ValueError):
    """Reject malformed or mutable evidence before commercial evaluation.

    Candidate metadata can influence a supply-chain migration decision, so the
    evaluator accepts only immutable primitive evidence with exact digest and
    version shapes. It never repairs or guesses malformed package metadata.
    """


@dataclass(frozen=True, slots=True)
class PostgresDriverCandidateEvidence:
    """Describe one validated PostgreSQL-driver package candidate.

    ``source_commit_sha`` identifies the reviewed source revision and
    ``artifact_sha256`` identifies the exact distributable under evaluation.
    ``python_versions`` and ``capabilities`` must contain explicit evidence rather
    than inferred support from a nearby release or similar database driver.
    Evaluation revalidates a fresh snapshot because Python's frozen dataclasses do
    not make ``object.__setattr__`` an authority boundary.
    """

    package_name: str
    package_version: str
    license_spdx: str
    python_versions: tuple[str, ...]
    source_commit_sha: str
    artifact_sha256: str
    capabilities: frozenset[str]

    def __post_init__(self) -> None:
        """Validate candidate evidence without normalizing ambiguous inputs."""
        for label, value in (
            ("package name", self.package_name),
            ("package version", self.package_version),
            ("license", self.license_spdx),
        ):
            if type(value) is not str or not value.strip():
                raise PostgresDriverCandidateEvidenceError(
                    f"PostgreSQL driver {label} evidence is invalid"
                )
        if type(self.python_versions) is not tuple or not self.python_versions:
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
        if type(self.capabilities) is not frozenset or not self.capabilities:
            raise PostgresDriverCandidateEvidenceError(
                "PostgreSQL driver capability evidence is invalid"
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
            python_versions=evidence.python_versions,
            source_commit_sha=evidence.source_commit_sha,
            artifact_sha256=evidence.artifact_sha256,
            capabilities=evidence.capabilities,
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
    closed when the SPDX identifier is not in the repository's explicitly
    reviewed permissive set, Python 3.14 support is not evidenced, or any runtime
    capability required by the migration port is absent. Reasons are deterministic
    so CI and acquisition diligence can compare exact evidence.
    """
    snapshot = _validated_candidate_snapshot(evidence)
    reasons: list[str] = []
    if snapshot.license_spdx not in _APPROVED_PERMISSIVE_LICENSES:
        reasons.append("license_not_approved")
    if "3.14" not in snapshot.python_versions:
        reasons.append("python_3_14_not_evidenced")
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
