# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for bounded PostgreSQL WAL manifest continuity."""

from __future__ import annotations

import pytest

from pg_llm_batch.postgres_wal_continuity import (
    PostgresWalContinuityError,
    assess_postgres_wal_continuity,
)

_MIB = 1024 * 1024


def test_contiguous_manifest_crosses_log_id_boundary() -> None:
    """A canonical 16 MiB archive can cross the WAL filename log-id boundary."""
    assessment = assess_postgres_wal_continuity(
        wal_segment_size_bytes=16 * _MIB,
        timeline_id=1,
        start_lsn="0/FF000000",
        target_lsn="1/00000000",
        segment_names=(
            "0000000100000000000000FF",
            "000000010000000100000000",
        ),
    )

    assert assessment.as_dict() == {
        "schema_version": 1,
        "timeline_id": 1,
        "wal_segment_size_bytes": 16 * _MIB,
        "start_lsn": "0/FF000000",
        "target_lsn": "1/00000000",
        "first_segment_name": "0000000100000000000000FF",
        "last_segment_name": "000000010000000100000000",
        "segment_count": 2,
        "archive_bytes_verified": False,
        "timeline_ancestry_verified": False,
        "replay_verified": False,
    }


def test_nondefault_segment_size_uses_postgres_filename_geometry() -> None:
    """A reviewed nondefault WAL segment size changes segment numbering correctly."""
    assessment = assess_postgres_wal_continuity(
        wal_segment_size_bytes=64 * _MIB,
        timeline_id=7,
        start_lsn="2/00000000",
        target_lsn="2/07FFFFFF",
        segment_names=(
            "000000070000000200000000",
            "000000070000000200000001",
        ),
    )

    assert assessment.segment_count == 2
    assert assessment.first_segment_name == "000000070000000200000000"
    assert assessment.last_segment_name == "000000070000000200000001"


def test_manifest_gap_fails_closed_without_echoing_names() -> None:
    """A missing required segment is not continuous archive evidence."""
    missing = "0000000100000000000000FE"
    with pytest.raises(
        PostgresWalContinuityError,
        match="^PostgreSQL WAL manifest is not exactly continuous$",
    ) as caught:
        assess_postgres_wal_continuity(
            wal_segment_size_bytes=16 * _MIB,
            timeline_id=1,
            start_lsn="0/FD000000",
            target_lsn="0/FF000000",
            segment_names=(
                "0000000100000000000000FD",
                missing,
            ),
        )
    assert missing not in str(caught.value)


def test_manifest_rejects_duplicate_out_of_order_and_wrong_timeline() -> None:
    """Exact ordered canonical names are required rather than a loose set match."""
    cases = (
        (
            "000000010000000000000001",
            "000000010000000000000001",
        ),
        (
            "000000010000000000000002",
            "000000010000000000000001",
        ),
        (
            "000000020000000000000001",
            "000000020000000000000002",
        ),
    )
    for segment_names in cases:
        with pytest.raises(
            PostgresWalContinuityError,
            match="^PostgreSQL WAL manifest is not exactly continuous$",
        ):
            assess_postgres_wal_continuity(
                wal_segment_size_bytes=16 * _MIB,
                timeline_id=1,
                start_lsn="0/01000000",
                target_lsn="0/02000000",
                segment_names=segment_names,
            )


def test_partial_or_noncanonical_names_fail_before_comparison() -> None:
    """Incomplete, lowercase, or otherwise noncanonical archive names fail closed."""
    for segment_name in (
        "000000010000000000000001.partial",
        "00000001000000000000000a",
        "00000001000000000000001",
    ):
        with pytest.raises(
            PostgresWalContinuityError,
            match="^invalid PostgreSQL WAL segment manifest$",
        ):
            assess_postgres_wal_continuity(
                wal_segment_size_bytes=16 * _MIB,
                timeline_id=1,
                start_lsn="0/01000000",
                target_lsn="0/01000000",
                segment_names=(segment_name,),
            )


def test_hostile_name_subclass_is_rejected_without_rendering() -> None:
    """Caller-defined string behavior cannot execute while validating a manifest."""

    class HostileString(str):
        def __str__(self) -> str:
            raise AssertionError("must not render hostile WAL name")

    with pytest.raises(
        PostgresWalContinuityError,
        match="^invalid PostgreSQL WAL segment manifest$",
    ):
        assess_postgres_wal_continuity(
            wal_segment_size_bytes=16 * _MIB,
            timeline_id=1,
            start_lsn="0/01000000",
            target_lsn="0/01000000",
            segment_names=(HostileString("000000010000000000000001"),),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("wal_segment_size_bytes", True),
        ("wal_segment_size_bytes", 0),
        ("wal_segment_size_bytes", 3 * _MIB),
        ("wal_segment_size_bytes", 2048 * _MIB),
        ("timeline_id", True),
        ("timeline_id", 0),
        ("timeline_id", 1 << 32),
        ("start_lsn", b"0/0"),
        ("start_lsn", "0x0/0"),
        ("start_lsn", "000000000/0"),
        ("target_lsn", None),
        ("target_lsn", "0/100000000"),
        ("segment_names", ["000000010000000000000000"]),
    ],
)
def test_invalid_inputs_use_one_content_free_error(field: str, value: object) -> None:
    """Exact primitive types and PostgreSQL bounds are validated fail closed."""
    arguments: dict[str, object] = {
        "wal_segment_size_bytes": 16 * _MIB,
        "timeline_id": 1,
        "start_lsn": "0/0",
        "target_lsn": "0/0",
        "segment_names": ("000000010000000000000000",),
    }
    arguments[field] = value
    with pytest.raises(
        PostgresWalContinuityError,
        match="^invalid PostgreSQL WAL continuity request$",
    ):
        assess_postgres_wal_continuity(**arguments)  # type: ignore[arg-type]


def test_target_must_not_precede_start() -> None:
    """A backwards target cannot define one forward archive continuity interval."""
    with pytest.raises(
        PostgresWalContinuityError,
        match="^PostgreSQL WAL target precedes archive start$",
    ):
        assess_postgres_wal_continuity(
            wal_segment_size_bytes=16 * _MIB,
            timeline_id=1,
            start_lsn="1/00000000",
            target_lsn="0/FF000000",
            segment_names=("000000010000000100000000",),
        )


def test_manifest_work_is_bounded_before_expected_names_are_built() -> None:
    """An attacker cannot force unbounded expected-segment materialization."""
    with pytest.raises(
        PostgresWalContinuityError,
        match="^PostgreSQL WAL continuity span exceeds bounded segment budget$",
    ):
        assess_postgres_wal_continuity(
            wal_segment_size_bytes=1 * _MIB,
            timeline_id=1,
            start_lsn="0/0",
            target_lsn="1/00000000",
            segment_names=(),
        )


def test_single_segment_target_is_supported() -> None:
    """Start and target inside one segment require exactly that segment."""
    assessment = assess_postgres_wal_continuity(
        wal_segment_size_bytes=16 * _MIB,
        timeline_id=0xA,
        start_lsn="16/B0000000",
        target_lsn="16/B0000100",
        segment_names=("0000000A00000016000000B0",),
    )

    assert assessment.segment_count == 1
    assert assessment.start_lsn == "16/B0000000"
    assert assessment.target_lsn == "16/B0000100"
    assert assessment.archive_bytes_verified is False
    assert assessment.replay_verified is False
