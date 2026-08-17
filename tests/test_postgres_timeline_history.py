# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for bounded PostgreSQL timeline-history evidence."""

from __future__ import annotations

import hashlib

import pytest

from pg_llm_batch.postgres_timeline_history import (
    PostgresTimelineHistoryError,
    assess_postgres_timeline_history,
)


def test_postgres_history_structure_normalizes_switchpoints_without_exporting_reasons() -> None:
    """PostgreSQL-style history lines become bounded content-free ancestry evidence."""
    history_content = (
        b"# archived timeline history\n"
        b"1\t0/1000000\tno recovery target specified\n"
        b"2\t0/02000000\toperator reason with sensitive prose\n"
    )

    assessment = assess_postgres_timeline_history(
        target_timeline_id=3,
        history_content=history_content,
    )

    assert assessment.as_dict() == {
        "schema_version": 1,
        "target_timeline_id": 3,
        "ancestor_timeline_ids": (1, 2),
        "switchpoints": ("0/01000000", "0/02000000"),
        "history_content_sha256": hashlib.sha256(history_content).hexdigest(),
        "history_structure_verified": True,
        "archive_provenance_verified": False,
        "replay_verified": False,
    }
    assert "sensitive" not in repr(assessment)


def test_comments_blank_lines_and_non_utf8_reason_bytes_are_ignored() -> None:
    """Authority fields parse without decoding untrusted human-readable reasons."""
    assessment = assess_postgres_timeline_history(
        target_timeline_id=2,
        history_content=(
            b"\n\t  # comment after leading whitespace\r\n"
            b"1\tA/B\toperator-\xff-reason\n"
        ),
    )

    assert assessment.ancestor_timeline_ids == (1,)
    assert assessment.switchpoints == ("A/0000000B",)


def test_timeline_one_accepts_only_comment_or_blank_history() -> None:
    """Timeline 1 has no parent history while preserving deterministic evidence."""
    assessment = assess_postgres_timeline_history(
        target_timeline_id=1,
        history_content=b"# no parent history\n\n",
    )

    assert assessment.ancestor_timeline_ids == ()
    assert assessment.switchpoints == ()
    assert assessment.history_structure_verified is True


@pytest.mark.parametrize(
    ("target_timeline_id", "history_content"),
    [
        (True, b""),
        (0, b""),
        (1 << 32, b""),
        (2, "1\t0/1"),
        (2, bytearray(b"1\t0/1")),
        (2, b"x" * 65537),
    ],
)
def test_invalid_request_types_bounds_and_budget_fail_closed(
    target_timeline_id: object,
    history_content: object,
) -> None:
    """Exact primitive types and a finite raw-history byte budget are mandatory."""
    with pytest.raises(
        PostgresTimelineHistoryError,
        match="^invalid PostgreSQL timeline history request$",
    ):
        assess_postgres_timeline_history(
            target_timeline_id=target_timeline_id,  # type: ignore[arg-type]
            history_content=history_content,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "history_content",
    [
        b"1\n",
        b"not-a-number\t0/1\n",
        b"1\tmissing-lsn\n",
        b"1\t0/100000000\n",
        b"1\t000000000/1\n",
        b"1\t0x0/1\n",
        b"0\t0/1\n",
        b"4294967296\t0/1\n",
    ],
)
def test_invalid_authority_fields_fail_with_content_free_syntax_error(
    history_content: bytes,
) -> None:
    """Malformed timeline/LSN authority never escapes through diagnostics."""
    with pytest.raises(
        PostgresTimelineHistoryError,
        match="^invalid PostgreSQL timeline history entry$",
    ) as caught:
        assess_postgres_timeline_history(
            target_timeline_id=3,
            history_content=history_content,
        )
    assert "not-a-number" not in str(caught.value)


def test_parent_timeline_ids_must_increase_and_remain_below_child() -> None:
    """History ancestry follows PostgreSQL's increasing-parent/child ordering rule."""
    cases = (
        b"",
        b"2\t0/1\n1\t0/2\n",
        b"1\t0/1\n1\t0/2\n",
        b"1\t0/1\n3\t0/2\n",
    )
    for history_content in cases:
        with pytest.raises(
            PostgresTimelineHistoryError,
            match="^invalid PostgreSQL timeline history ancestry$",
        ):
            assess_postgres_timeline_history(
                target_timeline_id=3,
                history_content=history_content,
            )


def test_switchpoints_must_not_move_backwards_along_ancestry() -> None:
    """A child-history chain cannot define overlapping backwards WAL intervals."""
    with pytest.raises(
        PostgresTimelineHistoryError,
        match="^invalid PostgreSQL timeline history switchpoint order$",
    ):
        assess_postgres_timeline_history(
            target_timeline_id=4,
            history_content=b"1\t0/20\n2\t0/10\n3\t0/30\n",
        )


def test_equal_switchpoints_are_kept_for_zero_length_intermediate_timeline() -> None:
    """Nondecreasing switchpoints preserve PostgreSQL-compatible zero-length ranges."""
    assessment = assess_postgres_timeline_history(
        target_timeline_id=3,
        history_content=b"1\t0/10\n2\t0/10\n",
    )

    assert assessment.switchpoints == ("0/00000010", "0/00000010")
