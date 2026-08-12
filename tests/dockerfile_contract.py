# SPDX-License-Identifier: Apache-2.0
"""Shared helpers for command-aware Dockerfile supply-chain assertions."""

from __future__ import annotations

import re
import shlex


_SHELL_COMMAND_BOUNDARY = re.compile(r"(?:&&|\|\||;|\n)")
_LINE_CONTINUATION = re.compile(r"\\[ \t]*\r?\n[ \t]*")


def dockerfile_uses_apt_get_upgrade(dockerfile: str) -> bool:
    """Return whether any shell command invokes ``apt-get ... upgrade``.

    Dockerfile line continuations are normalized before shell-like tokenization,
    so formatting changes and options between ``apt-get`` and ``upgrade`` cannot
    bypass the regression contract.
    """
    normalized = _LINE_CONTINUATION.sub(" ", dockerfile)
    for command in _SHELL_COMMAND_BOUNDARY.split(normalized):
        tokens = shlex.split(command, comments=True, posix=True)
        for index, token in enumerate(tokens):
            if token == "apt-get" and "upgrade" in tokens[index + 1 :]:
                return True
    return False
