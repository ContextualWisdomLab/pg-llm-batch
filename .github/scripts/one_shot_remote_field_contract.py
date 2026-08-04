# SPDX-License-Identifier: Apache-2.0
"""Prepare, implement, and document one durable remote-field hardening cycle."""

from __future__ import annotations

import argparse
from pathlib import Path

TEST_MARKER = "test_remote_field_contract_rejects_invalid_optional_ids"

TESTS = r'''


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("input_file_id", "file\x00shadow"),
        ("output_file_id", "o" * 257),
        ("error_file_id", "é"),
    ],
)
def test_remote_field_contract_rejects_invalid_optional_ids_before_database_access(
    monkeypatch: Any,
    field: str,
    value: str,
) -> None:
    """Every present provider file identifier is validated before PostgreSQL."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)

    with pytest.raises(ValueError, match=field):
        db.persist_remote_batch_state(
            "postgresql://example",
            "primary",
            {"id": "batch-1", field: value},
            observation_order=5,
        )

    assert driver.connections == []
    assert driver.executions == []


async def test_remote_field_contract_blocks_invalid_optional_id_before_custom_recorder() -> None:
    """A successful provider response cannot send an invalid file ID to a recorder."""
    recorded: list[dict[str, Any]] = []
    session = _ProviderSession(
        _ProviderResponse(
            {
                "id": "batch-1",
                "status": "completed",
                "output_file_id": "o" * 257,
            }
        )
    )

    def recorder(
        _dsn: str,
        _alias: str,
        provider_batch: Any,
        _observation_order: int,
    ) -> None:
        recorded.append(dict(provider_batch))

    client = DurableBatchAPIClient(
        "postgresql://example",
        lambda _alias: GatewayCredentials(
            url="https://gateway.example/v1",
            api_key="secret",
        ),
        lifecycle_recorder=recorder,
        observation_reserver=lambda _dsn: 1,
    )
    client._session = session

    with pytest.raises(GatewayError, match="persistence failed") as caught:
        await client.create_batch_job("file-1", "primary")

    assert caught.value.response_data["phase"] == "persistence"
    assert caught.value.response_data["error_type"] == "ValidationError"
    assert recorded == []
    assert session.post_urls == ["https://gateway.example/v1/batches"]


async def test_remote_field_contract_sanitizes_nul_text_before_custom_recorder() -> None:
    """Custom recorders receive safe endpoint and status text after remote success."""
    recorded: list[dict[str, Any]] = []
    session = _ProviderSession(
        _ProviderResponse(
            {
                "id": "batch-1",
                "endpoint": "/v1/responses\x00shadow",
                "status": "completed\x00shadow",
            }
        )
    )

    def recorder(
        _dsn: str,
        _alias: str,
        provider_batch: Any,
        _observation_order: int,
    ) -> None:
        recorded.append(dict(provider_batch))

    client = DurableBatchAPIClient(
        "postgresql://example",
        lambda _alias: GatewayCredentials(
            url="https://gateway.example/v1",
            api_key="secret",
        ),
        lifecycle_recorder=recorder,
        observation_reserver=lambda _dsn: 1,
    )
    client._session = session

    await client.create_batch_job("file-1", "primary")

    assert recorded[0]["endpoint"] is None
    assert recorded[0]["status"] == "unknown"
    assert "\x00" not in repr(recorded)


def test_remote_field_contract_normalizes_nul_optional_text(
    monkeypatch: Any,
) -> None:
    """NUL-bearing descriptive provider text cannot reach PostgreSQL columns."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)

    snapshot = db.persist_remote_batch_state(
        "postgresql://example",
        "primary",
        {
            "id": "batch-1",
            "endpoint": "/v1/responses\x00shadow",
            "status": "completed\x00shadow",
        },
        observation_order=6,
    )

    assert snapshot["batch_endpoint"] is None
    assert snapshot["batch_status"] == "unknown"
    assert "\x00" not in repr(driver.executions[0][1])


def test_remote_field_contract_adds_database_checks() -> None:
    """The canonical schema constrains every stored remote resource identifier."""
    schema = Path(db.SCHEMA_PATH).read_text(encoding="utf-8")
    pattern = "~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'"

    assert schema.count(pattern) == 4
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact source fragment or fail with actionable evidence."""
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def prepare_tests() -> None:
    """Append the failing regression contract exactly once."""
    path = Path("tests/test_remote_batch_state_contracts.py")
    text = path.read_text(encoding="utf-8")
    if TEST_MARKER not in text:
        path.write_text(text.rstrip() + TESTS + "\n", encoding="utf-8")


def write_evidence(pre_fix_head: str) -> None:
    """Record the exact red command and root-cause boundary."""
    path = Path(
        "docs/superpowers/evidence/2026-08-04-remote-field-contract-red.md"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Durable Remote Field Contract Red Evidence\n\n"
        f"- Pre-fix head: `{pre_fix_head}`\n"
        "- Command: `uv run pytest -q "
        "tests/test_remote_batch_state_contracts.py -k remote_field_contract`\n"
        "- Expected result: failure before implementation\n"
        "- Observed boundary: optional provider file identifiers and NUL-bearing\n"
        "  descriptive text could reach custom recorders or PostgreSQL without\n"
        "  the documented durable gateway validation contract.\n",
        encoding="utf-8",
    )


def apply_code() -> None:
    """Apply shared application and schema validation at the trust boundary."""
    db_path = Path("pg_llm_batch/db.py")
    source = db_path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '''def _provider_text(value: Any) -> Optional[str]:
    """Return a non-empty provider string or ``None`` for untrusted values."""
    return value if isinstance(value, str) and value else None
''',
        '''def normalize_optional_provider_text(value: Any) -> Optional[str]:
    """Return NUL-free provider text or ``None`` for unsafe optional values."""
    return (
        value
        if isinstance(value, str) and value and "\\x00" not in value
        else None
    )
''',
        "provider text NUL boundary",
    )
    marker = '''def _provider_metadata(value: Any) -> tuple[Dict[str, Any], str]:
'''
    helpers = '''def validate_optional_remote_resource_id(
    value: Any,
    field: str,
) -> Optional[str]:
    """Validate a present optional provider identifier or preserve absence.

    ``None`` and the empty string represent an omitted optional Batch object
    field. Every other value must satisfy the same bounded ASCII path-segment
    contract as required remote batch identifiers.
    """
    if value is None or value == "":
        return None
    return validate_remote_resource_id(value, field)


def _persisted_remote_resource_id(value: Any, field: str) -> Optional[str]:
    """Map optional identifier validation to the persistence helper contract."""
    try:
        return validate_optional_remote_resource_id(value, field)
    except ValidationError as exc:
        raise ValueError(
            f"{field} must be a supported optional remote resource identifier"
        ) from exc


'''
    source = replace_once(
        source,
        marker,
        helpers + marker,
        "optional remote identifier validator",
    )
    source = replace_once(
        source,
        '''    status_value = provider_batch.get("status")
    batch_status = (
        status_value
        if isinstance(status_value, str) and status_value
        else "unknown"
    )
''',
        '''    input_file_id = _persisted_remote_resource_id(
        provider_batch.get("input_file_id"),
        "input_file_id",
    )
    output_file_id = _persisted_remote_resource_id(
        provider_batch.get("output_file_id"),
        "output_file_id",
    )
    error_file_id = _persisted_remote_resource_id(
        provider_batch.get("error_file_id"),
        "error_file_id",
    )
    batch_status = (
        normalize_optional_provider_text(provider_batch.get("status"))
        or "unknown"
    )
''',
        "provider resource field normalization",
    )
    source = replace_once(
        source,
        '''        "input_file_id": _provider_text(provider_batch.get("input_file_id")),
        "batch_endpoint": _provider_text(provider_batch.get("endpoint")),
        "batch_status": batch_status,
        "output_file_id": _provider_text(provider_batch.get("output_file_id")),
        "error_file_id": _provider_text(provider_batch.get("error_file_id")),
''',
        '''        "input_file_id": input_file_id,
        "batch_endpoint": normalize_optional_provider_text(
            provider_batch.get("endpoint")
        ),
        "batch_status": batch_status,
        "output_file_id": output_file_id,
        "error_file_id": error_file_id,
''',
        "curated resource snapshot",
    )
    db_path.write_text(source, encoding="utf-8")

    durable_path = Path("pg_llm_batch/durable_client.py")
    durable = durable_path.read_text(encoding="utf-8")
    durable = replace_once(
        durable,
        '''    persist_remote_batch_state,
    reserve_remote_batch_observation_order,
    validate_endpoint_alias,
    validate_remote_resource_id,
''',
        '''    normalize_optional_provider_text,
    persist_remote_batch_state,
    reserve_remote_batch_observation_order,
    validate_endpoint_alias,
    validate_optional_remote_resource_id,
    validate_remote_resource_id,
''',
        "durable validation imports",
    )
    durable = replace_once(
        durable,
        '''            normalized_snapshot = dict(provider_batch)
            normalized_snapshot["id"] = validated_batch_id
            await asyncio.to_thread(
''',
        '''            normalized_snapshot = dict(provider_batch)
            normalized_snapshot["id"] = validated_batch_id
            for resource_field in (
                "input_file_id",
                "output_file_id",
                "error_file_id",
            ):
                normalized_snapshot[resource_field] = (
                    validate_optional_remote_resource_id(
                        normalized_snapshot.get(resource_field),
                        resource_field,
                    )
                )
            normalized_snapshot["endpoint"] = normalize_optional_provider_text(
                normalized_snapshot.get("endpoint")
            )
            normalized_snapshot["status"] = (
                normalize_optional_provider_text(normalized_snapshot.get("status"))
                or "unknown"
            )
            await asyncio.to_thread(
''',
        "durable recorder resource validation",
    )
    durable_path.write_text(durable, encoding="utf-8")

    old_table = '''    remote_batch_id TEXT NOT NULL
        CHECK (LENGTH(remote_batch_id) BETWEEN 1 AND 256),
    observation_order BIGINT NOT NULL
        CHECK (observation_order > 0),
    input_file_id TEXT,
    batch_endpoint TEXT,
    batch_status TEXT NOT NULL,
    output_file_id TEXT,
    error_file_id TEXT,
'''
    new_table = '''    remote_batch_id TEXT NOT NULL
        CHECK (LENGTH(remote_batch_id) BETWEEN 1 AND 256)
        CHECK (remote_batch_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'),
    observation_order BIGINT NOT NULL
        CHECK (observation_order > 0),
    input_file_id TEXT
        CHECK (
            input_file_id IS NULL OR
            input_file_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
        ),
    batch_endpoint TEXT,
    batch_status TEXT NOT NULL,
    output_file_id TEXT
        CHECK (
            output_file_id IS NULL OR
            output_file_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
        ),
    error_file_id TEXT
        CHECK (
            error_file_id IS NULL OR
            error_file_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
        ),
'''
    for schema_path in (
        Path("pg_llm_batch/schema.sql"),
        Path("docker/postgres/init/02_schema.sql"),
    ):
        schema = schema_path.read_text(encoding="utf-8")
        schema = replace_once(
            schema,
            old_table,
            new_table,
            f"remote identifier constraints in {schema_path}",
        )
        schema_path.write_text(schema, encoding="utf-8")


def apply_docs() -> None:
    """Align operator documentation, release notes, and APA references."""
    docs_path = Path("docs/remote-batch-lifecycle.md")
    docs = docs_path.read_text(encoding="utf-8")
    docs = replace_once(
        docs,
        '''Caller-provided batch identifiers are validated before
reservation. Provider-returned batch identifiers are validated before any
lifecycle recorder receives them. These application checks align with the
PostgreSQL storage constraints and prevent avoidable
remote-success/local-persistence split-brain failures.
''',
        '''Caller-provided batch identifiers are validated before
reservation. Provider-returned batch identifiers and every present input,
output, or error file identifier are validated before any lifecycle recorder or
PostgreSQL write receives them. The lifecycle table repeats the same identifier
syntax as database `CHECK` constraints. NUL-bearing optional endpoint text is
discarded and a NUL-bearing status becomes `unknown`, because PostgreSQL text
values cannot store the code-zero character. These boundaries prevent avoidable
remote-success/local-persistence split-brain failures.
''',
        "operator identifier contract",
    )
    if "*Character types*" not in docs:
        reference = (
            "\nPostgreSQL Global Development Group. (2026). *Character types*. "
            "In\n*PostgreSQL 18 documentation*.\n"
            "https://www.postgresql.org/docs/current/datatype-character.html\n"
        )
        docs = docs.replace(
            "\nPostgreSQL Global Development Group. (2026). "
            "*Conditional expressions*.",
            reference
            + "\nPostgreSQL Global Development Group. (2026). "
            "*Conditional expressions*.",
            1,
        )
    docs_path.write_text(docs, encoding="utf-8")

    changelog_path = Path("CHANGELOG.md")
    changelog = changelog_path.read_text(encoding="utf-8")
    changelog = replace_once(
        changelog,
        '''- Enforced NUL-free, 128-character endpoint aliases and 256-character remote
  resource identifiers before order reservation, credential resolution,
  provider calls, custom lifecycle recorders, or PostgreSQL writes.
''',
        '''- Enforced NUL-free, 128-character endpoint aliases and 256-character remote
  batch, input, output, and error file identifiers before order reservation,
  credential resolution, provider calls, custom lifecycle recorders, or
  PostgreSQL writes; NUL-bearing optional provider text is normalized safely.
''',
        "changelog remote field contract",
    )
    changelog_path.write_text(changelog, encoding="utf-8")


def main() -> None:
    """Execute the requested one-shot phase."""
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare-tests", "apply", "evidence"))
    parser.add_argument("--head", default="")
    args = parser.parse_args()

    if args.phase == "prepare-tests":
        prepare_tests()
    elif args.phase == "apply":
        apply_code()
        apply_docs()
    else:
        if not args.head:
            raise SystemExit("--head is required for evidence")
        write_evidence(args.head)


if __name__ == "__main__":
    main()
