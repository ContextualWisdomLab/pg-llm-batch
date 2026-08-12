# SPDX-License-Identifier: Apache-2.0
"""Regression tests for container-native PostgreSQL log routing."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "docker/postgres/postgresql.conf.custom"
DOCTORING = ROOT / "docs/doctoring/postgresql-logging-privacy.md"


def _settings() -> dict[str, str]:
    """Parse active scalar PostgreSQL settings from the optional profile."""
    settings: dict[str, str] = {}
    for raw_line in CONFIG.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        settings[key.strip()] = value.split("#", 1)[0].strip().strip("'\"")
    return settings


def test_container_profile_routes_operational_logs_to_stderr_without_collector() -> None:
    """The reviewed container profile must delegate retention to runtime logging."""
    settings = _settings()

    assert settings["logging_collector"].lower() == "off"
    assert settings["log_destination"].lower() == "stderr"


def test_container_native_routing_preserves_content_safe_logging_boundary() -> None:
    """Changing log routing must not re-enable SQL, bind, or connection-event copies."""
    settings = _settings()

    assert settings["log_statement"].lower() == "none"
    assert settings["log_min_duration_statement"] == "-1"
    assert settings["log_parameter_max_length"] == "0"
    assert settings["log_parameter_max_length_on_error"] == "0"
    assert settings["log_connections"].lower() == "off"
    assert settings["log_disconnections"].lower() == "off"
    assert settings["pg_stat_statements.track"].lower() == "none"


def test_container_logging_doctoring_preserves_restart_and_autovacuum_truth() -> None:
    """Operator guidance must distinguish restart and active autovacuum logging semantics."""
    doctoring = DOCTORING.read_text(encoding="utf-8")

    assert "changing `logging_collector` requires a **PostgreSQL restart**" in doctoring
    assert "`log_autovacuum_min_duration = 10min` remains active" in doctoring
    assert "Both event classes remain an **opt-in**" not in doctoring
