# SPDX-License-Identifier: Apache-2.0
"""Canonical product documents must not persist transient pull-request state."""

from __future__ import annotations

import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_STATUS_DOCUMENTS = (
    REPOSITORY_ROOT / "docs" / "product" / "PRD.md",
    REPOSITORY_ROOT / "docs" / "product" / "TRD.md",
    REPOSITORY_ROOT / "docs" / "DOCUMENTATION_FITNESS.md",
    REPOSITORY_ROOT / "docs" / "TRACEABILITY.md",
    REPOSITORY_ROOT / "docs" / "adr" / "README.md",
)
_TRANSIENT_PR_STATE = re.compile(
    r"(?i)\b(?:draft|ready)\s+#\d+\b|\bpr\s+#\d+\s+remains\s+draft\b"
)
_EXACT_HEAD_SHA = re.compile(r"\b[0-9a-f]{40}\b")
_PROTECTED_MAIN_REFERENCE_TREE = "d2f1e32271910a6db98a0757d67194ddadca4566"


def _read(path: Path) -> str:
    """Return one canonical Markdown document as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_canonical_status_documents_omit_transient_pr_ready_or_draft_labels() -> None:
    """Durable product/status prose must not freeze Draft/Ready pull-request labels."""
    for path in CANONICAL_STATUS_DOCUMENTS:
        matches = _TRANSIENT_PR_STATE.findall(_read(path))
        assert matches == [], f"{path.name} persists transient PR state: {matches}"


def test_canonical_status_documents_do_not_embed_exact_contributor_heads() -> None:
    """Exact SHAs belong in review evidence, not durable product-status prose."""
    for path in CANONICAL_STATUS_DOCUMENTS:
        text = _read(path)
        leftover = [
            match
            for match in _EXACT_HEAD_SHA.findall(text)
            if match != _PROTECTED_MAIN_REFERENCE_TREE
        ]
        assert leftover == [], f"{path.name} embeds exact heads: {leftover}"


def test_product_contract_names_restore_successor_without_draft_label() -> None:
    """#209 is the unsafe predecessor; #212 is the unshipped active successor."""
    prd = _read(REPOSITORY_ROOT / "docs" / "product" / "PRD.md")
    trd = _read(REPOSITORY_ROOT / "docs" / "product" / "TRD.md")
    fitness = _read(REPOSITORY_ROOT / "docs" / "DOCUMENTATION_FITNESS.md")

    for document in (prd, trd, fitness):
        assert "Draft #212" not in document
        assert "#212" in document
        assert "#209" in document
        assert "EOF-consumption" in document or "EOF" in document


def test_product_contract_names_active_recovery_capability_families() -> None:
    """The recovery graph is more than logical dump/restore execution."""
    prd = _read(REPOSITORY_ROOT / "docs" / "product" / "PRD.md")
    fitness = _read(REPOSITORY_ROOT / "docs" / "DOCUMENTATION_FITNESS.md")
    traceability = _read(REPOSITORY_ROOT / "docs" / "TRACEABILITY.md")

    for document in (prd, fitness, traceability):
        assert "evidence binding" in document.lower() or "receipt" in document.lower()
        assert "catalog" in document.lower()
        assert "pitr" in document.lower()
        assert "target isolation" in document.lower() or "restore-target" in document.lower()


def test_canonical_overlay_register_names_current_successor_without_draft_instruction() -> None:
    """The durable register must name the live overlay and must not freeze Draft/Ready instructions."""
    traceability = _read(REPOSITORY_ROOT / "docs" / "TRACEABILITY.md")
    fitness = _read(REPOSITORY_ROOT / "docs" / "DOCUMENTATION_FITNESS.md")

    assert "#214" in traceability
    assert "superseded" in traceability.lower()
    assert "#226" in traceability
    assert "not the landing vehicle" in traceability
    assert "keep it Draft" not in traceability
    assert "keep it Ready" not in traceability
    assert "#225" in traceability
    assert "ADR 0022" in traceability
    assert "ADR 0021 collision" in traceability
    assert "#226" in fitness
    assert "superseded #214" in fitness
    assert "current canonical documentation landing vehicle" in traceability
