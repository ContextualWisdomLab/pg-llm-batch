# SPDX-License-Identifier: Apache-2.0
"""Regression tests for immutable lifecycle-outbox authorization bindings."""

import pytest

from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore


TENANT_SCOPE_SHA256 = "a" * 64


def test_store_authorization_binding_cannot_be_reassigned() -> None:
    """A validated store must not become a different tenant or database after admission."""
    store = PostgresContextLifecycleOutboxStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
        tenant_scope_sha256=TENANT_SCOPE_SHA256,
    )

    assert store.postgres_dsn == "postgresql://unit"
    assert store.tenant_scope == "tenant-a"
    assert store.tenant_scope_sha256 == TENANT_SCOPE_SHA256

    for attribute, replacement in (
        ("postgres_dsn", "postgresql://other"),
        ("tenant_scope", "tenant-b"),
        ("tenant_scope_sha256", "b" * 64),
    ):
        with pytest.raises(AttributeError):
            setattr(store, attribute, replacement)


def test_store_private_authorization_binding_cannot_be_rebound_or_deleted() -> None:
    """Private backing names must not bypass the admitted store authority boundary."""
    store = PostgresContextLifecycleOutboxStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
        tenant_scope_sha256=TENANT_SCOPE_SHA256,
    )

    for attribute, replacement in (
        ("_postgres_dsn", "postgresql://other"),
        ("_tenant_scope", "tenant-b"),
        ("_tenant_scope_sha256", "b" * 64),
    ):
        with pytest.raises(AttributeError):
            setattr(store, attribute, replacement)
        with pytest.raises(AttributeError):
            delattr(store, attribute)

    assert store.postgres_dsn == "postgresql://unit"
    assert store.tenant_scope == "tenant-a"
    assert store.tenant_scope_sha256 == TENANT_SCOPE_SHA256


def test_object_level_mutation_cannot_redirect_admitted_store_authority() -> None:
    """Bypassing frozen assignment must not replace or delete admitted DB/RLS authority."""
    store = PostgresContextLifecycleOutboxStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
        tenant_scope_sha256=TENANT_SCOPE_SHA256,
    )

    for attribute, replacement in (
        ("_postgres_dsn", "postgresql://other"),
        ("_tenant_scope", "tenant-b"),
        ("_tenant_scope_sha256", "b" * 64),
    ):
        with pytest.raises(AttributeError):
            object.__setattr__(store, attribute, replacement)
        with pytest.raises(AttributeError):
            object.__delattr__(store, attribute)

    assert store.postgres_dsn == "postgresql://unit"
    assert store.tenant_scope == "tenant-a"
    assert store.tenant_scope_sha256 == TENANT_SCOPE_SHA256
