# SPDX-License-Identifier: Apache-2.0
"""Canonical documentation contracts for tenant-scoped content-bearing state."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THREAT_MODEL = ROOT / "docs/THREAT_MODEL.md"
ERD = ROOT / "docs/architecture/ERD.md"
TRACEABILITY = ROOT / "docs/TRACEABILITY.md"


def _normalized(path: Path) -> str:
    """Return normalized lower-case Markdown for bounded semantic assertions."""
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_tenant_content_isolation_gap_has_cross_document_authority() -> None:
    """Issue #130 must remain explicit without overclaiming ACTIVE-PR #53."""
    threat = _normalized(THREAT_MODEL)
    erd = _normalized(ERD)
    trace = _normalized(TRACEABILITY)

    for phrase in (
        "cross-tenant content-bearing work-state disclosure",
        "planned #130",
        "llm_queues",
        "llm_requests",
        "active-pr #53",
        "not end-to-end tenant isolation",
    ):
        assert phrase in threat, phrase

    for phrase in (
        "issue #130",
        "not tenant-qualified",
        "llm_queues",
        "llm_requests",
        "active-pr #53",
        "remote lifecycle",
    ):
        assert phrase in erd, phrase

    for phrase in (
        "tenant-scoped content-bearing work state",
        "planned #130",
        "active-pr #53",
        "active-pr #87",
    ):
        assert phrase in trace, phrase
