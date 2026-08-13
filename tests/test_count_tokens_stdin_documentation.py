# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for bounded count-tokens standard-input privacy."""

from pathlib import Path

from pg_llm_batch import cli

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
DOCTORING = ROOT / "docs" / "doctoring" / "count-tokens-stdin-privacy.md"


def test_readme_uses_bounded_stdin_for_count_tokens() -> None:
    """The operator procedure must not reintroduce prompt content in argv."""
    text = README.read_text(encoding="utf-8")

    assert "count-tokens --model gpt-4o --stdin" in text
    assert "count-tokens --model gpt-4o --text" not in text
    assert "at most 1 MiB" in text
    assert "strict UTF-8" in text


def test_doctoring_matches_cli_byte_limit_and_privacy_authority() -> None:
    """Doctoring must bind the implementation ceiling and primary references."""
    text = DOCTORING.read_text(encoding="utf-8")

    assert f"{cli.MAX_TOKEN_INPUT_BYTES:,} bytes" in text
    assert "ACTIVE-PR #173" in text
    assert "CWE-214" in text
    assert "https://cwe.mitre.org/data/definitions/214.html" in text
    assert "Python 3.14.6" in text
    assert "https://docs.python.org/3.14/library/sys.html#sys.argv" in text


def test_readme_does_not_claim_retired_sql_provider_authority() -> None:
    """The root architecture must not advertise the retired SQL retriever."""
    text = README.read_text(encoding="utf-8")

    assert "(or) pg_cron job" not in text
    assert "former bundled `pg_cron` + `pgsql-http` provider retriever is\nretired" in text
