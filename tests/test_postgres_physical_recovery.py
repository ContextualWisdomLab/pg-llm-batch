# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for bounded physical/WAL/PITR recovery profiles."""

from __future__ import annotations

import json

import pytest

from pg_llm_batch.postgres_physical_recovery import (
    PostgresPhysicalRecoveryError,
    PostgresPhysicalRecoveryProfile,
    bind_postgres_physical_recovery_profile,
    parse_postgres_physical_recovery_profile,
)


def _profile(**overrides: object) -> PostgresPhysicalRecoveryProfile:
    arguments: dict[str, object] = {
        "postgres_major": 18,
        "backup_method": "pitr",
        "recovery_target_kind": "time",
        "wal_archive_required": True,
        "isolated_target_prepared": True,
        "rpo_seconds": 300,
        "rto_seconds": 3600,
    }
    arguments.update(overrides)
    return bind_postgres_physical_recovery_profile(**arguments)  # type: ignore[arg-type]


def test_pitr_time_profile_is_deterministic_and_not_a_capability_claim() -> None:
    """A realistic PostgreSQL 18 time-flow PITR profile stays content-free."""
    profile = _profile()

    assert profile.as_dict() == {
        "schema_version": 1,
        "postgres_major": 18,
        "backup_method": "pitr",
        "recovery_target_kind": "time",
        "wal_archive_required": True,
        "isolated_target_prepared": True,
        "rpo_seconds": 300,
        "rto_seconds": 3600,
        "package_capability_claim": False,
    }
    assert profile.to_json() == (
        '{"backup_method":"pitr","isolated_target_prepared":true,'
        '"package_capability_claim":false,"postgres_major":18,'
        '"recovery_target_kind":"time","rpo_seconds":300,"rto_seconds":3600,'
        '"schema_version":1,"wal_archive_required":true}'
    )


def test_physical_immediate_profile_allows_crash_consistent_base_backup() -> None:
    """A physical base backup may omit WAL when the target kind is immediate."""
    profile = _profile(
        backup_method="physical",
        recovery_target_kind="immediate",
        wal_archive_required=False,
        rpo_seconds=None,
        rto_seconds=None,
    )

    assert profile.backup_method == "physical"
    assert profile.wal_archive_required is False
    assert profile.as_dict()["rpo_seconds"] is None
    assert profile.as_dict()["package_capability_claim"] is False


def test_physical_immediate_profile_may_archive_wal_without_claiming_pitr() -> None:
    """Archiving WAL does not let a physical profile claim a time-flow target."""
    profile = _profile(
        backup_method="physical",
        recovery_target_kind="immediate",
        wal_archive_required=True,
    )

    assert profile.wal_archive_required is True
    assert profile.recovery_target_kind == "immediate"


@pytest.mark.parametrize("kind", ["time", "xid", "name", "lsn"])
def test_point_in_time_kinds_require_pitr_method(kind: str) -> None:
    """Time-flow restore kinds cannot be attached to a physical-only profile."""
    with pytest.raises(
        PostgresPhysicalRecoveryError,
        match="^PostgreSQL point-in-time target requires a PITR profile$",
    ):
        _profile(
            backup_method="physical",
            recovery_target_kind=kind,
            wal_archive_required=True,
        )


def test_pitr_method_requires_wal_archive() -> None:
    """PITR without a WAL archive is not a usable time-flow recovery contract."""
    with pytest.raises(
        PostgresPhysicalRecoveryError,
        match="^PostgreSQL PITR profile requires a WAL archive$",
    ):
        _profile(backup_method="pitr", wal_archive_required=False)


def test_profile_requires_isolated_target() -> None:
    """Physical or PITR restore must start in an isolated recovery target."""
    with pytest.raises(
        PostgresPhysicalRecoveryError,
        match="^PostgreSQL physical recovery requires an isolated target$",
    ):
        _profile(isolated_target_prepared=False)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("postgres_major", True),
        ("postgres_major", 0),
        ("postgres_major", 100),
        ("backup_method", "logical"),
        ("backup_method", "snapshot"),
        ("recovery_target_kind", "latest"),
        ("recovery_target_kind", "immediate "),
        ("wal_archive_required", 1),
        ("isolated_target_prepared", 1),
        ("rpo_seconds", 0),
        ("rpo_seconds", True),
        ("rpo_seconds", -1),
        ("rpo_seconds", 1 << 63),
        ("rto_seconds", 0),
        ("rto_seconds", True),
        ("rto_seconds", 1 << 63),
    ],
)
def test_profile_rejects_invalid_metadata(field: str, value: object) -> None:
    """Exact types and reviewed enumerations fail closed before any capability claim."""
    with pytest.raises(
        PostgresPhysicalRecoveryError,
        match="^invalid PostgreSQL physical recovery profile$",
    ):
        _profile(**{field: value})


def test_profile_rejects_hostile_string_subclass() -> None:
    """Subclassed method strings cannot sneak past the exact-type contract."""

    class HostileString(str):
        def __str__(self) -> str:
            raise AssertionError("must not render hostile metadata")

    with pytest.raises(
        PostgresPhysicalRecoveryError,
        match="^invalid PostgreSQL physical recovery profile$",
    ):
        _profile(backup_method=HostileString("pitr"))


def test_parse_round_trips_exact_pitr_profile() -> None:
    """Hosts can persist and reload the exact machine-readable profile."""
    profile = _profile(recovery_target_kind="lsn", rpo_seconds=None)

    assert parse_postgres_physical_recovery_profile(profile.to_json()) == profile


def test_parse_rejects_non_string() -> None:
    """Binary or object input is not a profile document."""
    with pytest.raises(
        PostgresPhysicalRecoveryError,
        match="^invalid PostgreSQL physical recovery profile JSON$",
    ):
        parse_postgres_physical_recovery_profile(b"{}")  # type: ignore[arg-type]


def test_parse_rejects_empty_or_oversized_document() -> None:
    """The profile document stays inside a fixed content-free byte budget."""
    with pytest.raises(
        PostgresPhysicalRecoveryError,
        match="^invalid PostgreSQL physical recovery profile JSON$",
    ):
        parse_postgres_physical_recovery_profile("")
    with pytest.raises(
        PostgresPhysicalRecoveryError,
        match="^invalid PostgreSQL physical recovery profile JSON$",
    ):
        parse_postgres_physical_recovery_profile("{" + ("a" * 2048) + "}")


def test_parse_rejects_malformed_json() -> None:
    """Broken JSON cannot become a recovery profile."""
    with pytest.raises(
        PostgresPhysicalRecoveryError,
        match="^invalid PostgreSQL physical recovery profile JSON$",
    ):
        parse_postgres_physical_recovery_profile("{")


def test_parse_rejects_recursive_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parser recursion failures stay inside the content-free JSON error."""

    def exploding_load(*_args: object, **_kwargs: object) -> object:
        raise RecursionError("secret recursion")

    monkeypatch.setattr(json, "loads", exploding_load)
    with pytest.raises(
        PostgresPhysicalRecoveryError,
        match="^invalid PostgreSQL physical recovery profile JSON$",
    ) as caught:
        parse_postgres_physical_recovery_profile('{"schema_version":1}')
    assert "secret" not in str(caught.value)


def test_parse_rejects_duplicate_keys() -> None:
    """Duplicate JSON members are ambiguous evidence and must fail closed."""
    profile = _profile()
    raw = profile.to_json().replace(
        '"backup_method":"pitr"',
        '"backup_method":"pitr","backup_method":"physical"',
        1,
    )
    with pytest.raises(
        PostgresPhysicalRecoveryError,
        match="^invalid PostgreSQL physical recovery profile schema$",
    ):
        parse_postgres_physical_recovery_profile(raw)


def test_parse_rejects_unknown_or_missing_keys() -> None:
    """The profile schema is closed; extra or missing members are invalid."""
    payload = _profile().as_dict()
    payload["extra_field"] = True
    with pytest.raises(
        PostgresPhysicalRecoveryError,
        match="^invalid PostgreSQL physical recovery profile schema$",
    ):
        parse_postgres_physical_recovery_profile(json.dumps(payload))
    payload = _profile().as_dict()
    del payload["backup_method"]
    with pytest.raises(
        PostgresPhysicalRecoveryError,
        match="^invalid PostgreSQL physical recovery profile schema$",
    ):
        parse_postgres_physical_recovery_profile(json.dumps(payload))
    with pytest.raises(
        PostgresPhysicalRecoveryError,
        match="^invalid PostgreSQL physical recovery profile schema$",
    ):
        parse_postgres_physical_recovery_profile("[]")


@pytest.mark.parametrize("schema_version", [2, True, "1"])
def test_parse_rejects_non_v1_schema(schema_version: object) -> None:
    """Only exact integer schema version 1 is accepted."""
    payload = _profile().as_dict()
    payload["schema_version"] = schema_version
    with pytest.raises(
        PostgresPhysicalRecoveryError,
        match="^invalid PostgreSQL physical recovery profile schema$",
    ):
        parse_postgres_physical_recovery_profile(json.dumps(payload))


@pytest.mark.parametrize("claim", [True, None, 0])
def test_parse_rejects_capability_claim(claim: object) -> None:
    """A persisted profile cannot assert that the package met RPO or RTO."""
    payload = _profile().as_dict()
    payload["package_capability_claim"] = claim
    with pytest.raises(
        PostgresPhysicalRecoveryError,
        match="^PostgreSQL physical recovery profile cannot claim package capability$",
    ):
        parse_postgres_physical_recovery_profile(json.dumps(payload))


def test_bind_does_not_execute_backup_or_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    """The binder is evidence-only; it must not start PostgreSQL recovery tools."""

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("physical recovery profile must not execute tools")

    monkeypatch.setattr("os.system", forbidden)
    profile = bind_postgres_physical_recovery_profile(
        postgres_major=18,
        backup_method="pitr",
        recovery_target_kind="xid",
        wal_archive_required=True,
        isolated_target_prepared=True,
    )
    assert profile.recovery_target_kind == "xid"
