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


def test_optional_timing_metrics_are_opt_in_for_predictable_overhead() -> None:
    """Timing metrics with platform-dependent cost must remain explicit opt-ins."""
    settings = _settings()
    doctoring = " ".join(DOCTORING.read_text(encoding="utf-8").lower().split())

    assert settings["track_io_timing"].lower() == "off"
    assert settings["track_wal_io_timing"].lower() == "off"
    for phrase in (
        "track_io_timing",
        "track_wal_io_timing",
        "pg_test_timing",
        "timing overhead",
        "opt-in",
    ):
        assert phrase in doctoring, phrase


def test_function_statistics_are_opt_in_for_bounded_monitoring_overhead() -> None:
    """Function-call timing must not be enabled for every deployment by default."""
    settings = _settings()
    doctoring = " ".join(DOCTORING.read_text(encoding="utf-8").lower().split())

    assert settings["track_functions"].lower() == "none"
    for phrase in (
        "track_functions",
        "function statistics",
        "statistics collection",
        "overhead",
        "opt-in",
    ):
        assert phrase in doctoring, phrase


def test_commit_timestamp_tracking_is_opt_in_for_bounded_transaction_metadata() -> None:
    """Commit timestamps must not create extra transaction metadata without purpose."""
    settings = _settings()
    doctoring = " ".join(DOCTORING.read_text(encoding="utf-8").lower().split())

    assert settings["track_commit_timestamp"].lower() == "off"
    for phrase in (
        "track_commit_timestamp",
        "pg_commit_ts",
        "server start",
        "default is off",
        "opt-in",
    ):
        assert phrase in doctoring, phrase


def test_high_volume_temp_and_autovacuum_logging_is_not_unconditionally_enabled() -> None:
    """Generic monitoring must not emit every temp-file and autovacuum event."""
    settings = _settings()
    doctoring = " ".join(DOCTORING.read_text(encoding="utf-8").lower().split())

    assert settings["log_temp_files"] == "-1"
    assert settings["log_autovacuum_min_duration"] == "10min"
    for phrase in (
        "log_temp_files",
        "temporary file names and sizes",
        "log_autovacuum_min_duration",
        "logs all autovacuum actions",
        "10min",
        "opt-in",
    ):
        assert phrase in doctoring, phrase


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


def test_connection_event_logging_is_opt_in_and_network_metadata_is_documented() -> None:
    """Connection events must not create avoidable client-network log copies."""
    settings = _settings()
    doctoring = " ".join(DOCTORING.read_text(encoding="utf-8").lower().split())

    assert settings["log_connections"].lower() == "off"
    assert settings["log_disconnections"].lower() == "off"
    for phrase in (
        "client host:port",
        "log_connections",
        "log_disconnections",
        "client network metadata",
        "opt-in",
    ):
        assert phrase in doctoring, phrase


def test_optional_query_statistics_do_not_retain_query_text_without_opt_in() -> None:
    """Representative query-text collection must be disabled in the package baseline."""
    settings = _settings()

    assert settings["pg_stat_statements.track"].lower() == "none"
    assert settings["pg_stat_statements.track_utility"].lower() == "off"
    assert settings["pg_stat_statements.track_planning"].lower() == "off"
    assert settings["pg_stat_statements.save"].lower() == "off"


def test_query_statistics_preload_is_opt_in_for_bounded_shared_memory() -> None:
    """Disabled query statistics must not still reserve preload/query-id resources."""
    settings = _settings()
    preloaded = {
        item.strip() for item in settings["shared_preload_libraries"].split(",")
    }

    assert "pg_stat_statements" not in preloaded
    assert settings["compute_query_id"].lower() == "auto"


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
