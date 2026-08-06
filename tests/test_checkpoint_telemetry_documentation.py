# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for durable checkpoint observability."""

from pathlib import Path

ROOT = Path(__file__).parents[1]


def normalized(path: str) -> str:
    """Read one project document with layout-insensitive whitespace."""
    return " ".join((ROOT / path).read_text(encoding="utf-8").split())


def test_authoritative_documents_define_checkpoint_telemetry_boundary() -> None:
    """Architecture and contributor contracts state the safe signal boundary."""
    required = {
        "ARCHITECTURE.md": (
            "OpenTelemetryCheckpointStore",
            "tenant, consumer, batch, endpoint, file, digest, cursor, and DSN values",
            "best-effort telemetry cannot change checkpoint operation semantics",
        ),
        "AGENTS.md": (
            "OpenTelemetry checkpoint signals",
            "record_exception=False",
            "set_status_on_exception=False",
            "finite low-cardinality `error.type`",
        ),
        "CLAUDE.md": (
            "OpenTelemetry checkpoint signals",
            "Never add tenant, consumer, batch, endpoint, file, digest, cursor, or DSN values",
            "telemetry failures must not mask or replace application results or exceptions",
        ),
        "CHANGELOG.md": (
            "OpenTelemetry-compatible checkpoint spans and metrics",
            "checkpoint_conflict, validation_error, and internal_error",
        ),
        "docs/checkpoint-observability.md": (
            "The wrapper delegates all arguments and returns unchanged",
            "Package-owned telemetry never contains tenant scope",
            "The wrapper supplies `(None, None, None)` when closing the span context",
            "Non-cancellation process-control exceptions remain outside this observer-failure guarantee",
        ),
    }
    for path, phrases in required.items():
        text = normalized(path)
        for phrase in phrases:
            assert phrase in text, f"{path} must contain {phrase!r}"


def test_adr_and_doctoring_record_operator_and_standards_contracts() -> None:
    """The decision record and doctoring cite authoritative telemetry evidence."""
    adr = normalized("docs/adr/0008-checkpoint-opentelemetry-observability.md")
    doctoring = normalized(
        "docs/doctoring/checkpoint-opentelemetry-observability.md"
    )
    for phrase in (
        "dependency-injected OpenTelemetry-compatible tracer and meter",
        "package-owned spans and metrics never contain resource identifiers",
        "histogram unit is seconds",
        "exporter, processor, sampler, and provider ownership remains with the host",
        "rollback",
    ):
        assert phrase in adr
    for phrase in (
        "OpenTelemetry semantic conventions 1.43.0",
        "Semantic conventions for database client spans",
        "Recording errors",
        "error.type SHOULD be predictable and SHOULD have low cardinality",
        "db.system.name",
        "postgresql",
        "APA 7",
    ):
        assert phrase in doctoring
