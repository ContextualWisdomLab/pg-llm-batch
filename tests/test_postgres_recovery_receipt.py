# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for bounded PostgreSQL recovery receipts."""

from __future__ import annotations

import json

import pytest

from pg_llm_batch.postgres_recovery_receipt import (
    PostgresRecoveryReceipt,
    PostgresRecoveryReceiptError,
    parse_postgres_recovery_receipt,
)


COMMIT = "a" * 40
SCHEMA_SHA256 = "b" * 64
BACKUP_SHA256 = "c" * 64


def _receipt(**overrides: object) -> PostgresRecoveryReceipt:
    arguments: dict[str, object] = {
        "package_version": "0.1.0",
        "source_commit": COMMIT,
        "postgres_major": 18,
        "schema_sha256": SCHEMA_SHA256,
        "backup_method": "logical",
        "backup_sha256": BACKUP_SHA256,
        "backup_size_bytes": 4096,
        "started_at_epoch": 1_786_800_000,
        "completed_at_epoch": 1_786_800_030,
    }
    arguments.update(overrides)
    return PostgresRecoveryReceipt(**arguments)  # type: ignore[arg-type]


def test_receipt_is_deterministic_and_content_free() -> None:
    receipt = _receipt()

    assert receipt.as_dict() == {
        "schema_version": 1,
        "package_version": "0.1.0",
        "source_commit": COMMIT,
        "postgres_major": 18,
        "schema_sha256": SCHEMA_SHA256,
        "backup_method": "logical",
        "backup_sha256": BACKUP_SHA256,
        "backup_size_bytes": 4096,
        "started_at_epoch": 1_786_800_000,
        "completed_at_epoch": 1_786_800_030,
    }
    assert receipt.to_json() == (
        '{"backup_method":"logical","backup_sha256":"'
        + BACKUP_SHA256
        + '","backup_size_bytes":4096,"completed_at_epoch":1786800030,'
        '"package_version":"0.1.0","postgres_major":18,"schema_sha256":"'
        + SCHEMA_SHA256
        + '","schema_version":1,"source_commit":"'
        + COMMIT
        + '","started_at_epoch":1786800000}'
    )


@pytest.mark.parametrize("method", ["logical", "physical", "pitr"])
def test_receipt_supports_reviewed_backup_methods(method: str) -> None:
    assert _receipt(backup_method=method).backup_method == method


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("package_version", ""),
        ("package_version", "1/secret"),
        ("source_commit", "A" * 40),
        ("source_commit", "abc"),
        ("postgres_major", True),
        ("postgres_major", 0),
        ("postgres_major", 100),
        ("schema_sha256", "g" * 64),
        ("backup_method", "snapshot"),
        ("backup_sha256", "C" * 64),
        ("backup_size_bytes", True),
        ("backup_size_bytes", 0),
        ("backup_size_bytes", 1 << 63),
        ("started_at_epoch", -1),
        ("completed_at_epoch", 1 << 63),
        ("completed_at_epoch", 1_786_799_999),
    ],
)
def test_receipt_rejects_invalid_metadata(field: str, value: object) -> None:
    with pytest.raises(
        PostgresRecoveryReceiptError,
        match="invalid PostgreSQL recovery receipt metadata",
    ):
        _receipt(**{field: value})


def test_receipt_rejects_hostile_string_subclass_without_rendering() -> None:
    class HostileString(str):
        def __str__(self) -> str:
            raise AssertionError("must not render hostile metadata")

        def __hash__(self) -> int:
            raise AssertionError("must not hash hostile metadata")

        def __eq__(self, other: object) -> bool:
            raise AssertionError("must not compare hostile metadata")

    with pytest.raises(PostgresRecoveryReceiptError):
        _receipt(backup_method=HostileString("logical"))


def test_parse_round_trips_exact_receipt() -> None:
    receipt = _receipt(backup_method="pitr")

    assert parse_postgres_recovery_receipt(receipt.to_json()) == receipt


def test_parse_rejects_duplicate_keys() -> None:
    raw_receipt = _receipt().to_json()
    duplicate = raw_receipt.replace(
        '"schema_version":1',
        '"schema_version":1,"schema_version":1',
    )

    with pytest.raises(PostgresRecoveryReceiptError, match="receipt schema"):
        parse_postgres_recovery_receipt(duplicate)


@pytest.mark.parametrize(
    "raw_receipt",
    [
        "",
        "not-json",
        " " * 2049,
        "[]",
        '{"schema_version":2}',
        '{"schema_version":true}',
    ],
)
def test_parse_rejects_malformed_or_unbounded_receipts(raw_receipt: str) -> None:
    with pytest.raises(PostgresRecoveryReceiptError):
        parse_postgres_recovery_receipt(raw_receipt)


def test_parse_rejects_maximum_depth_json_with_package_error() -> None:
    raw_receipt = "[" * 1023 + "0" + "]" * 1023

    assert len(raw_receipt.encode("utf-8")) == 2047
    with pytest.raises(PostgresRecoveryReceiptError, match="receipt"):
        parse_postgres_recovery_receipt(raw_receipt)


def test_parse_normalizes_decoder_recursion_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decoder_detail = "decoder recursion detail must stay private"

    def fail_decode(*_args: object, **_kwargs: object) -> object:
        raise RecursionError(decoder_detail)

    monkeypatch.setattr(json, "loads", fail_decode)
    with pytest.raises(PostgresRecoveryReceiptError, match="receipt JSON") as raised:
        parse_postgres_recovery_receipt(_receipt().to_json())

    assert decoder_detail not in str(raised.value)


def test_parse_rejects_surrogate_text() -> None:
    with pytest.raises(PostgresRecoveryReceiptError, match="receipt JSON"):
        parse_postgres_recovery_receipt("\ud800")


@pytest.mark.parametrize("schema_version", [2, True])
def test_parse_rejects_wrong_schema_version(schema_version: object) -> None:
    payload = _receipt().as_dict()
    payload["schema_version"] = schema_version

    with pytest.raises(PostgresRecoveryReceiptError, match="receipt schema"):
        parse_postgres_recovery_receipt(json.dumps(payload))


def test_parse_rejects_unknown_fields() -> None:
    payload = _receipt().as_dict()
    payload["dsn"] = "postgresql://user:password@example.invalid/db"

    with pytest.raises(PostgresRecoveryReceiptError, match="receipt schema"):
        parse_postgres_recovery_receipt(json.dumps(payload))


def test_parse_rejects_invalid_field_metadata_without_reflection() -> None:
    payload = _receipt().as_dict()
    payload["backup_method"] = "secret-provider-message"

    with pytest.raises(PostgresRecoveryReceiptError) as raised:
        parse_postgres_recovery_receipt(json.dumps(payload))

    assert "secret-provider-message" not in str(raised.value)


def test_parse_rejects_non_string_input() -> None:
    with pytest.raises(PostgresRecoveryReceiptError, match="receipt JSON"):
        parse_postgres_recovery_receipt(b"{}")  # type: ignore[arg-type]
