# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for the optional PostgreSQL logging configuration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "docker/postgres/postgresql.conf.custom"


def _settings() -> dict[str, str]:
    """Return active ``key = value`` settings with trailing comments removed."""
    settings: dict[str, str] = {}
    for raw_line in CONFIG.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        settings[key.strip()] = value.split("#", 1)[0].strip().strip("'\"")
    return settings


def test_optional_postgres_logging_does_not_capture_sql_or_bind_values_by_default() -> None:
    """The reviewed baseline must not persist prompt/secret-bearing SQL text."""
    settings = _settings()

    assert settings["log_statement"] == "none"
    assert settings["log_min_duration_statement"] == "-1"
    assert settings["log_min_duration_sample"] == "-1"
    assert settings["log_statement_sample_rate"] == "0"
    assert settings["log_transaction_sample_rate"] == "0"
    assert settings["log_duration"].lower() == "off"
    assert settings["log_min_error_statement"].lower() == "panic"
    assert settings["log_parameter_max_length"] == "0"
    assert settings["log_parameter_max_length_on_error"] == "0"
    assert settings["log_error_verbosity"].lower() == "terse"


def test_optional_query_statistics_do_not_retain_query_text_without_opt_in() -> None:
    """Representative query-text collection must be disabled in the package baseline."""
    settings = _settings()

    assert settings["pg_stat_statements.track"].lower() == "none"
    assert settings["pg_stat_statements.track_utility"].lower() == "off"
    assert settings["pg_stat_statements.track_planning"].lower() == "off"
    assert settings["pg_stat_statements.save"].lower() == "off"


def test_optional_postgres_logging_does_not_claim_blanket_sql_logging_is_compliance() -> None:
    """Operator guidance must not equate plaintext SQL retention with compliance."""
    normalized = " ".join(CONFIG.read_text(encoding="utf-8").lower().split())

    for prohibited in (
        "log everything for complete audit trail",
        "required for data security",
        "minimum for compliance",
        "financial: 7 years",
        "healthcare: 6 years",
        "eu data: 6 years",
    ):
        assert prohibited not in normalized, prohibited
