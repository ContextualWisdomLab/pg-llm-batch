# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for the optional PostgreSQL logging configuration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "docker/postgres/postgresql.conf.custom"
DOCTORING = ROOT / "docs/doctoring/postgresql-logging-privacy.md"


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


def test_csv_logging_enables_the_required_logging_collector() -> None:
    """A configured CSV destination must enable PostgreSQL's logging collector."""
    settings = _settings()
    destinations = {item.strip() for item in settings["log_destination"].split(",")}

    assert "csvlog" in destinations
    assert settings["logging_collector"].lower() == "on"


def test_csv_logging_collector_contract_is_documented() -> None:
    """Doctoring must explain routing, restart, and retention semantics."""
    doctoring = " ".join(DOCTORING.read_text(encoding="utf-8").lower().split())

    for phrase in (
        "logging_collector",
        "csvlog",
        "server start",
        "log routing",
        "does not define retention",
    ):
        assert phrase in doctoring, phrase


def test_optional_query_statistics_do_not_retain_query_text_without_opt_in() -> None:
    """Representative query-text collection must be disabled in the package baseline."""
    settings = _settings()

    assert settings["pg_stat_statements.track"].lower() == "none"
    assert settings["pg_stat_statements.track_utility"].lower() == "off"
    assert settings["pg_stat_statements.track_planning"].lower() == "off"
    assert settings["pg_stat_statements.save"].lower() == "off"


def test_activity_tracking_query_text_residual_is_explicit() -> None:
    """Live pg_stat_activity query text must remain an explicit residual boundary."""
    settings = _settings()
    doctoring = " ".join(DOCTORING.read_text(encoding="utf-8").lower().split())

    assert settings["track_activities"].lower() == "on"
    assert settings["track_activity_query_size"] == "1024"
    for phrase in (
        "pg_stat_activity",
        "query text",
        "track_activities",
        "volatile",
        "pg_read_all_stats",
    ):
        assert phrase in doctoring, phrase


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
