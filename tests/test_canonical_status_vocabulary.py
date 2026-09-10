# SPDX-License-Identifier: Apache-2.0
"""Canonical product documents must track durable protected-main capability truth."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from pg_llm_batch.config import SecretStore


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_STATUS_DOCUMENTS = (
    REPOSITORY_ROOT / "docs" / "product" / "PRD.md",
    REPOSITORY_ROOT / "docs" / "product" / "TRD.md",
    REPOSITORY_ROOT / "docs" / "DOCUMENTATION_FITNESS.md",
    REPOSITORY_ROOT / "docs" / "TRACEABILITY.md",
    REPOSITORY_ROOT / "docs" / "adr" / "README.md",
)
_SECRET_POLICY_DOCUMENTS = (
    REPOSITORY_ROOT / "docs" / "product" / "PRD.md",
    REPOSITORY_ROOT / "docs" / "product" / "TRD.md",
    REPOSITORY_ROOT / "docs" / "DATA_GOVERNANCE.md",
    REPOSITORY_ROOT / "docs" / "THREAT_MODEL.md",
    REPOSITORY_ROOT / "docs" / "DOCUMENTATION_FITNESS.md",
    REPOSITORY_ROOT / "docs" / "TRACEABILITY.md",
)
_TRANSIENT_PR_STATE = re.compile(
    r"(?i)\b(?:draft|ready)\s+#\d+\b|\bpr\s+#\d+\s+remains\s+draft\b"
)
_EXACT_HEAD_SHA = re.compile(r"\b[0-9a-f]{40}\b")
_ACTIVE_OVERLAY_ENTRY = re.compile(r"(?m)^- \*\*#(?P<number>\d+)\*\*")


def _read(path: Path) -> str:
    """Return one canonical Markdown document as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_canonical_status_documents_omit_transient_pr_ready_or_draft_labels() -> None:
    """Durable product/status prose must not freeze Draft/Ready pull-request labels."""
    for path in CANONICAL_STATUS_DOCUMENTS:
        matches = _TRANSIENT_PR_STATE.findall(_read(path))
        assert matches == [], f"{path.name} persists transient PR state: {matches}"


def test_canonical_status_documents_do_not_embed_exact_heads() -> None:
    """Exact contributor or protected SHAs belong in review evidence, not durable prose."""
    for path in CANONICAL_STATUS_DOCUMENTS:
        matches = _EXACT_HEAD_SHA.findall(_read(path))
        assert matches == [], f"{path.name} embeds exact heads: {matches}"


def test_product_contract_records_integrated_logical_restore_boundary() -> None:
    """Merged #212 is shipped only as the bounded direct logical-restore executor."""
    prd = _read(REPOSITORY_ROOT / "docs" / "product" / "PRD.md")
    trd = _read(REPOSITORY_ROOT / "docs" / "product" / "TRD.md")
    fitness = _read(REPOSITORY_ROOT / "docs" / "DOCUMENTATION_FITNESS.md")
    traceability = _read(REPOSITORY_ROOT / "docs" / "TRACEABILITY.md")

    assert "| PostgreSQL logical restore execution | IMPLEMENTED-ON-PROTECTED-MAIN |" in prd
    assert "Direct `pg_restore` execution is **IMPLEMENTED-ON-PROTECTED-MAIN**" in trd
    assert "logical restore executor is protected-main behavior" in fitness
    assert "| FR-5 executable PostgreSQL logical restore | IMPLEMENTED-ON-PROTECTED-MAIN |" in traceability
    for document in (prd, trd, fitness, traceability):
        assert "#212" in document
        assert "#209" in document
        assert "EOF" in document
        assert "RPO/RTO" in document or "RPO" in document


def test_product_contract_records_integrated_single_flight_without_lease_claim() -> None:
    """Merged #191 is a transient session advisory lock, not a scheduler or durable lease."""
    prd = _read(REPOSITORY_ROOT / "docs" / "product" / "PRD.md")
    trd = _read(REPOSITORY_ROOT / "docs" / "product" / "TRD.md")
    traceability = _read(REPOSITORY_ROOT / "docs" / "TRACEABILITY.md")

    assert "| Cross-process reconciliation single-flight | IMPLEMENTED-ON-PROTECTED-MAIN |" in prd
    assert "session advisory single-flight" in trd
    assert "| FR-4 tenant-qualified cross-process single-flight | IMPLEMENTED-ON-PROTECTED-MAIN |" in traceability
    for document in (prd, trd, traceability):
        lowered = document.lower()
        assert "durable lease" in lowered
        assert "scheduler" in lowered
        assert "distributed exactly-once" in lowered


def test_product_contract_records_integrated_restore_target_identity_boundary() -> None:
    """Merged #228 proves bounded name-plus-cluster separation, not end-to-end restore safety."""
    prd = _read(REPOSITORY_ROOT / "docs" / "product" / "PRD.md")
    trd = _read(REPOSITORY_ROOT / "docs" / "product" / "TRD.md")
    fitness = _read(REPOSITORY_ROOT / "docs" / "DOCUMENTATION_FITNESS.md")
    traceability = _read(REPOSITORY_ROOT / "docs" / "TRACEABILITY.md")
    adr_index = _read(REPOSITORY_ROOT / "docs" / "adr" / "README.md")

    assert "| PostgreSQL restore-target cluster identity verification | IMPLEMENTED-ON-PROTECTED-MAIN |" in prd
    assert "`postgres_restore_target.py`" in trd
    assert "merged #228" in fitness
    assert "| FR-5 restore-target cluster identity verification | IMPLEMENTED-ON-PROTECTED-MAIN |" in traceability
    assert "[0022](0022-postgres-restore-target-isolation.md)" in adr_index
    for document in (prd, trd, fitness, traceability, adr_index):
        lowered = document.lower()
        assert "system_identifier" in document
        assert "rpo/rto" in lowered or "rpo" in lowered


def test_secret_policy_docs_match_optional_fernet_compatibility_default() -> None:
    """Canonical secret prose must not turn optional Fernet into a shipped mandate."""
    parameter = inspect.signature(SecretStore).parameters["require_encryption"]
    assert parameter.default is False

    for path in _SECRET_POLICY_DOCUMENTS:
        text = _read(path)
        lowered = text.lower()
        if "secret" not in lowered:
            continue
        assert "optional fernet" in lowered or "fernet" in lowered
        assert "compatibility" in lowered
        assert "encrypted secrets are postgresql-backed" not in lowered
        assert "postgresql-backed configuration and encrypted secret storage" not in lowered


def test_active_overlay_register_excludes_merged_or_closed_recovery_predecessors() -> None:
    """The active register must not retain merged #191/#212/#228 or closed #225 as live work."""
    traceability = _read(REPOSITORY_ROOT / "docs" / "TRACEABILITY.md")
    active_numbers = {
        int(match.group("number")) for match in _ACTIVE_OVERLAY_ENTRY.finditer(traceability)
    }
    assert 191 not in active_numbers
    assert 212 not in active_numbers
    assert 225 not in active_numbers
    assert 228 not in active_numbers
    assert 296 in active_numbers
    assert 341 in active_numbers


def test_product_contract_names_active_recovery_capability_families() -> None:
    """The recovery graph remains broader than the integrated logical restore executor."""
    prd = _read(REPOSITORY_ROOT / "docs" / "product" / "PRD.md")
    fitness = _read(REPOSITORY_ROOT / "docs" / "DOCUMENTATION_FITNESS.md")
    traceability = _read(REPOSITORY_ROOT / "docs" / "TRACEABILITY.md")

    for document in (prd, fitness, traceability):
        assert "evidence binding" in document.lower() or "receipt" in document.lower()
        assert "catalog" in document.lower()
        assert "pitr" in document.lower()
        assert "target isolation" in document.lower() or "restore-target" in document.lower()


def test_canonical_overlay_register_preserves_superseded_lineage_without_live_status() -> None:
    """Historical predecessors may remain as lineage without becoming active overlays."""
    traceability = _read(REPOSITORY_ROOT / "docs" / "TRACEABILITY.md")
    fitness = _read(REPOSITORY_ROOT / "docs" / "DOCUMENTATION_FITNESS.md")

    assert "#214" in traceability
    assert "#226" in traceability
    assert "superseded" in traceability.lower()
    assert "keep it Draft" not in traceability
    assert "keep it Ready" not in traceability
    assert "#225" in traceability
    assert "superseded restore-target predecessor" in traceability
    assert "#226" in fitness
    assert "superseded #214" in fitness
    assert "current canonical documentation landing vehicle" in traceability
