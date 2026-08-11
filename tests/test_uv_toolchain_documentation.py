# SPDX-License-Identifier: Apache-2.0
"""Documentation contract for deterministic uv toolchain selection."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTORING = ROOT / "docs/doctoring/uv-toolchain-reproducibility.md"


def test_uv_toolchain_doctoring_records_reproducibility_and_recovery() -> None:
    """The exact uv pin must retain rationale, update, rollback, and standards."""
    assert DOCTORING.exists(), "missing uv toolchain reproducibility doctoring"

    raw = DOCTORING.read_text(encoding="utf-8").lower()
    normalized = " ".join(raw.split())

    assert 'required-version = "==0.12.3"' in raw
    assert "## update procedure" in raw
    assert "## rollback and recovery" in raw
    assert (
        "do not recover by deleting `uv.toml`, broadening the specifier, "
        "or selecting `latest`"
        in normalized
    )

    for phrase in (
        "falling back to latest",
        "setup-uv",
        "python 3.14",
        "astral software",
        "apa 7",
    ):
        assert phrase in normalized, phrase
