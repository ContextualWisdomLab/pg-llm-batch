# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for bootstrap-secret documentation accuracy."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_secret_claims_distinguish_provider_credentials_from_key_material() -> None:
    """Docs must not claim the environment contains no secrets while it can carry a Fernet key."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    threat_model = (ROOT / "docs/THREAT_MODEL.md").read_text(encoding="utf-8").lower()

    assert "no secrets in the environment" not in readme
    assert "provider credentials stay out of the environment" in readme
    assert "fernet key" in readme
    assert "sensitive bootstrap" in readme
    assert "bootstrap fernet key" in threat_model
    assert "secret material" in threat_model
