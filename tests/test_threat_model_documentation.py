# SPDX-License-Identifier: Apache-2.0
"""Static contracts for the protected-main threat-model overlay."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THREAT_MODEL = REPOSITORY_ROOT / "docs" / "THREAT_MODEL.md"
FITNESS = REPOSITORY_ROOT / "docs" / "DOCUMENTATION_FITNESS.md"


def _read(path: Path) -> str:
    """Return one Markdown document as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_threat_model_identifies_assets_boundaries_and_residuals() -> None:
    """A buyer must see assets, trust boundaries, mitigations, and residual risk."""
    text = _read(THREAT_MODEL)
    assert "tenant_scope" in text
    assert "llm_remote_batch_jobs" in text
    assert "llm_result_stream_checkpoints" in text
    assert "authorized business payloads" in text.lower() or "content fidelity" in text.lower()
    assert "set_config" in text
    assert "BYPASSRLS" in text
    assert "Residual" in text
    assert "does not claim" in text.lower() or "not a certification" in text.lower()


def test_threat_model_cites_current_risk_authorities() -> None:
    """Doctoring must cite current NIST risk and control publications in APA 7th."""
    text = " ".join(_read(THREAT_MODEL).split())
    assert "NIST Special Publication 800-53" in text
    assert "NIST Special Publication 800-30" in text
    assert "800-154" in text
    assert "https://doi.org/10.6028/NIST.SP.800-53r5" in text
    assert "https://doi.org/10.6028/NIST.SP.800-30r1" in text


def test_threat_model_tells_the_operator_the_next_action() -> None:
    """The document must tell a qualified host what to do next, not only what exists."""
    text = " ".join(_read(THREAT_MODEL).split())
    assert "Do not grant arbitrary SQL" in text or "do not grant arbitrary SQL" in text
    assert "standalone" in text


def test_fitness_inventory_tracks_the_threat_model_overlay() -> None:
    """The fitness matrix must stop calling the threat model merely planned."""
    fitness = _read(FITNESS)
    assert "docs/THREAT_MODEL.md" in fitness
    assert "| Threat model | PLANNED |" not in fitness
