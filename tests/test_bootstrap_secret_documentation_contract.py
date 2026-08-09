# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for bootstrap-secret documentation accuracy."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_secret_claims_distinguish_provider_credentials_from_key_material() -> None:
    """Public guidance must keep provider keys off argv and classify bootstrap keys."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    threat_model = (ROOT / "docs/THREAT_MODEL.md").read_text(encoding="utf-8").lower()

    assert "no secrets in the environment" not in readme
    assert (
        "by default, provider credentials stay out of the environment in standalone mode"
        in readme
    )
    assert "pg_llm_batch_secret_key" in readme
    assert "fernet key is sensitive bootstrap secret material" in readme
    assert "config set-secret gateway_api_key.default sk-your-key" not in readme
    assert "getpass.getpass" in readme
    assert "getpass.getpasswarning" in readme
    assert 'warnings.simplefilter("error", getpass.getpasswarning)' in readme
    assert "cannot disable terminal echo; refusing secret input" in readme
    assert "secretstore" in readme
    assert "set_secret" in readme
    assert "pip install '.[secrets]'" in readme
    assert "bootstrap fernet key" in threat_model
    assert "distinct from database-backed provider credentials" in threat_model
    assert "terminal echo control is unavailable" in threat_model
    assert "fails closed before accepting provider credential input" in threat_model
