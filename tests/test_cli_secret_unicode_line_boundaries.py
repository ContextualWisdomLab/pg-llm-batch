# SPDX-License-Identifier: Apache-2.0
"""Unicode and control-line boundary contracts for CLI secret ingestion."""

from __future__ import annotations

import pytest

from pg_llm_batch import cli
from pg_llm_batch.exceptions import ConfigError


@pytest.mark.parametrize(
    "separator",
    [
        "\v",  # vertical tab
        "\f",  # form feed
        "\x1c",  # file separator
        "\x1d",  # group separator
        "\x1e",  # record separator
        "\x85",  # next line
        "\u2028",  # line separator
        "\u2029",  # paragraph separator
    ],
)
def test_secret_validation_rejects_every_logical_line_separator(
    separator: str,
) -> None:
    """One-line secret input must reject non-LF logical line boundaries too."""
    secret = f"first{separator}second"

    with pytest.raises(ConfigError, match="single line") as exc_info:
        cli._validate_secret_input(secret)

    assert secret not in str(exc_info.value)


@pytest.mark.parametrize("separator", ["\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"])
def test_secret_validation_rejects_trailing_nonterminal_line_endings(
    separator: str,
) -> None:
    """Only the reader's terminal LF/CRLF normalization may remove framing."""
    with pytest.raises(ConfigError, match="single line"):
        cli._validate_secret_input(f"secret{separator}")
