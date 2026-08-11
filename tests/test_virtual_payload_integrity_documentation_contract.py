# SPDX-License-Identifier: Apache-2.0
"""Canonical documentation contract for persisted virtual JSONL integrity."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs/adr/virtual-jsonl-payload-integrity.md"
ADR_INDEX = ROOT / "docs/adr/README.md"


def _normalized(path: Path) -> str:
    """Return normalized lower-case Markdown for semantic assertions."""
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_virtual_payload_integrity_gap_has_canonical_owner() -> None:
    """Issue #124 must have one discoverable planned ADR without shipped claims."""
    adr = _normalized(ADR)
    index = _normalized(ADR_INDEX)

    for phrase in (
        "persisted virtual jsonl payload integrity",
        "status: planned — issue #124",
        "implementation baseline: protected `main` does **not** yet enforce",
        "llm_batch_file_payloads.content",
        "_persist_payloads()",
        "_normalize_payload_content()",
        "`text` containing the serialized jsonl",
        "`line_count` containing the assembled record count",
        "exact non-boolean non-negative integer",
        "agree with the validated persisted jsonl record/framing count",
        "before credential resolution",
        "before provider i/o",
        "fail closed",
        "prompt/request jsonl content must not be reflected",
        "python 3.10, 3.12, and 3.14",
        "100% owned production statement/branch coverage",
        "rfc 8259",
        "postgresql 18 documentation: json types",
        "postgresql 18 documentation: constraints",
    ):
        assert phrase in adr, phrase

    for phrase in (
        "issue #124",
        "planned persisted virtual jsonl payload-integrity boundary",
        "virtual-jsonl-payload-integrity.md",
        "before credential resolution or provider i/o",
    ):
        assert phrase in index, phrase

    assert "implemented-on-protected-main" not in adr.split("## context", 1)[0]
