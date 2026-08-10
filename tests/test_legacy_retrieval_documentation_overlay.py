# SPDX-License-Identifier: Apache-2.0
"""Canonical documentation contracts for retiring legacy SQL provider retrieval."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
FITNESS = ROOT / "docs/DOCUMENTATION_FITNESS.md"


def test_readme_labels_legacy_sql_retrieval_as_active_pr_retirement() -> None:
    """Do not present the deprecated pg_cron/pgsql-http path as a durable target."""
    readme = README.read_text(encoding="utf-8")

    assert "ACTIVE-PR #101" in readme
    assert "legacy direct-SQL" in readme
    assert "fresh databases" in readme
    assert "do not create `pg_cron` or `http`" in readme
    assert "Issue #102" in readme
    assert "(or) pg_cron job  cron_fetch_batch_results()  polls + imports results via pgsql-http" not in readme
    assert "PostgreSQL with `pg_tiktoken`, `pg_cron`, and `http`" not in readme


def test_documentation_fitness_tracks_extension_runtime_retirement_follow_up() -> None:
    """Keep the staged old-volume package/preload removal visible as planned work."""
    fitness = FITNESS.read_text(encoding="utf-8")

    planned = fitness.split("### PLANNED", 1)[1].split("### SUPERSEDED", 1)[0]
    assert "Issue #103" in planned
    assert "pg_cron" in planned
    assert "http" in planned
    assert "existing-volume" in planned
    assert "package" in planned
