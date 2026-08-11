# SPDX-License-Identifier: Apache-2.0
"""Canonical documentation contracts for newly verified reliability gaps."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRD = ROOT / "docs/product/TRD.md"
THREAT_MODEL = ROOT / "docs/THREAT_MODEL.md"
TRACEABILITY = ROOT / "docs/TRACEABILITY.md"
FITNESS = ROOT / "docs/DOCUMENTATION_FITNESS.md"


def _normalized(path: Path) -> str:
    """Return normalized lower-case Markdown for semantic assertions."""
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def _canonical_documents() -> dict[str, str]:
    """Return the documentation authorities shared by bounded gap contracts."""
    return {
        "trd": _normalized(TRD),
        "threat": _normalized(THREAT_MODEL),
        "traceability": _normalized(TRACEABILITY),
        "fitness": _normalized(FITNESS),
    }


def test_durable_lifecycle_failure_diagnostics_gap_has_canonical_owner() -> None:
    """Issue #125 must own the bounded lifecycle recovery-diagnostic target."""
    documents = _canonical_documents()

    for name, text in documents.items():
        for phrase in (
            "#125",
            "durable lifecycle",
            "dynamic exception",
            "finite",
        ):
            assert phrase in text, f"{name}: {phrase}"

    for phrase in (
        "reservation",
        "persistence",
        "__cause__",
        "tenant scope",
        "planned",
    ):
        assert phrase in documents["trd"], phrase


def test_tokenizer_metadata_docs_distinguish_absence_from_lookup_failure() -> None:
    """Issue #108 must reject fail-open metadata lookup ambiguity."""
    documents = _canonical_documents()

    for name, text in documents.items():
        assert "#108" in text, name
        assert "endpoint-qualified" in text, name

    for phrase in (
        "no matching metadata",
        "lookup failure",
        "must not silently",
        "bounded diagnostics",
    ):
        assert phrase in documents["trd"], phrase

    for phrase in (
        "lookup failure",
        "exception text",
        "tokenizer fallback",
    ):
        assert phrase in documents["threat"], phrase


def test_runtime_tokenizer_install_authority_gap_has_canonical_owner() -> None:
    """Issue #126 must separate extension provisioning from runtime counting."""
    documents = _canonical_documents()

    for name, text in documents.items():
        for phrase in (
            "#126",
            "pg_tiktoken",
            "runtime",
            "provision",
        ):
            assert phrase in text, f"{name}: {phrase}"

    for phrase in (
        "create extension",
        "read-only",
        "least privilege",
        "tokenizer fallback",
        "planned",
    ):
        assert phrase in documents["trd"], phrase


def test_durable_lifecycle_fields_gap_has_canonical_owner() -> None:
    """Issue #127 must bound durable provider status and endpoint fields."""
    documents = _canonical_documents()

    for name, text in documents.items():
        for phrase in (
            "#127",
            "batch_status",
            "batch_endpoint",
            "finite",
        ):
            assert phrase in text, f"{name}: {phrase}"

    for phrase in (
        "terminal",
        "cancelling",
        "provider",
        "durable",
        "planned",
    ):
        assert phrase in documents["trd"], phrase
