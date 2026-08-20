# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for post-construction recovery-receipt mutation."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from pg_llm_batch.postgres_recovery_receipt import (
    PostgresRecoveryReceipt,
    PostgresRecoveryReceiptError,
)


def _receipt() -> PostgresRecoveryReceipt:
    return PostgresRecoveryReceipt(
        package_version="0.1.0",
        source_commit="a" * 40,
        postgres_major=18,
        schema_sha256="b" * 64,
        backup_method="logical",
        backup_sha256="c" * 64,
        backup_size_bytes=4096,
        started_at_epoch=1_786_800_000,
        completed_at_epoch=1_786_800_030,
    )


def _as_dict(receipt: PostgresRecoveryReceipt) -> object:
    return receipt.as_dict()


def _to_json(receipt: PostgresRecoveryReceipt) -> object:
    return receipt.to_json()


@pytest.mark.parametrize("serialize", [_as_dict, _to_json])
def test_serialization_rejects_post_construction_unbounded_metadata(
    serialize: Callable[[PostgresRecoveryReceipt], object],
) -> None:
    receipt = _receipt()
    secret_detail = "deployment-secret/" + "x" * 4096
    object.__setattr__(receipt, "package_version", secret_detail)

    with pytest.raises(
        PostgresRecoveryReceiptError,
        match="invalid PostgreSQL recovery receipt metadata",
    ) as raised:
        serialize(receipt)

    assert secret_detail not in str(raised.value)


@pytest.mark.parametrize("serialize", [_as_dict, _to_json])
def test_serialization_normalizes_deleted_required_field(
    serialize: Callable[[PostgresRecoveryReceipt], object],
) -> None:
    receipt = _receipt()
    object.__delattr__(receipt, "source_commit")

    with pytest.raises(
        PostgresRecoveryReceiptError,
        match="invalid PostgreSQL recovery receipt metadata",
    ):
        serialize(receipt)
