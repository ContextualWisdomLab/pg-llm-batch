# SPDX-License-Identifier: Apache-2.0
"""Tests for trusted local tenant-scope validation."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.db import (
    DEFAULT_TENANT_SCOPE,
    MAX_TENANT_SCOPE_CHARACTERS,
    validate_tenant_scope,
)
from pg_llm_batch.exceptions import ValidationError


@pytest.mark.parametrize(
    "tenant_scope",
    [
        "standalone",
        "tenant-a",
        "Tenant_01",
        "tenant.example:region-1",
        "a" * 128,
    ],
)
def test_validate_tenant_scope_preserves_supported_ascii_values(
    tenant_scope: str,
) -> None:
    """Accepted tenant scopes are returned exactly without trimming or coercion."""
    assert validate_tenant_scope(tenant_scope) == tenant_scope


def test_default_tenant_scope_is_explicit_standalone_identity() -> None:
    """Legacy durable clients use one explicit, testable standalone scope."""
    assert DEFAULT_TENANT_SCOPE == "standalone"
    assert MAX_TENANT_SCOPE_CHARACTERS == 128
    assert validate_tenant_scope(DEFAULT_TENANT_SCOPE) == "standalone"


@pytest.mark.parametrize(
    "tenant_scope",
    [
        None,
        True,
        False,
        1,
        b"tenant-a",
        "",
        " tenant-a",
        "tenant-a ",
        "tenant/a",
        "tenant%2Fa",
        "tenant\x00a",
        "tenant\na",
        "테넌트-a",
        "a" * 129,
    ],
)
def test_validate_tenant_scope_rejects_ambiguous_or_unsafe_values(
    tenant_scope: Any,
) -> None:
    """Unsupported scope values fail with bounded structured diagnostics."""
    with pytest.raises(ValidationError) as exc_info:
        validate_tenant_scope(tenant_scope)

    assert exc_info.value.details == {
        "field": "tenant_scope",
        "value": tenant_scope,
        "reason": (
            "must be 1-128 ASCII characters beginning with an alphanumeric "
            "character and containing only letters, digits, dot, underscore, "
            "colon, or hyphen"
        ),
    }
