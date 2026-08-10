# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for provider-compatibility claims."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_qualifies_openai_compatible_provider_support() -> None:
    """README must not promise universal compatibility beyond verified behavior."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    api_contract = (ROOT / "docs/product/API_CONTRACT.md").read_text(encoding="utf-8")
    introduction = readme.split("Extracted from", 1)[0]

    assert "against any OpenAI-compatible Batch API" not in introduction
    assert "targets the OpenAI-compatible Files/Batches API shape" in introduction
    assert "compatibility is limited to documented and verified behavior" in introduction
    assert "does not promise compatibility with every undocumented provider extension" in api_contract
