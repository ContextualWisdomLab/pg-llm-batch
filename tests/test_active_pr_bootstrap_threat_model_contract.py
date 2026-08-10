# SPDX-License-Identifier: Apache-2.0
"""Security-document contract for the current bootstrap authority overlay."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_threat_model_tracks_bootstrap_exact_type_and_source_precedence() -> None:
    """PR #89's authority-type boundary must be explicit in the threat model."""
    threat = (ROOT / "docs/THREAT_MODEL.md").read_text(encoding="utf-8").lower()

    assert "#89" in threat
    assert "active-pr" in threat
    assert "explicit postgres dsn" in threat
    assert "explicit fernet" in threat
    assert "exact string" in threat
    assert "non-string" in threat
    assert "environment fallback" in threat
    assert "protected main" in threat
