# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Pure, interpreter-agnostic fuzz targets for pg-llm-batch.

Every ``fuzz_*`` function takes raw ``bytes`` (whatever the fuzzer / property
engine hands it), decodes it into arguments, drives the real production code,
and asserts the invariants that must hold for *arbitrary* input.

Contract for a target:

* It may raise :class:`AssertionError` — that is a genuine invariant violation
  (a finding).
* It may raise any exception that production code is *not* expected to raise for
  arbitrary input — also a finding.
* It must swallow the small, explicit set of exceptions that represent
  *documented / handled* failure modes (e.g. a malformed JSON line surfacing as
  ``json.JSONDecodeError``). Those are listed per-target below.

Keeping the assertions here (not in the harness) lets Atheris and Hypothesis
share exactly the same oracle.
"""

from __future__ import annotations

import json
from typing import List

from pg_llm_batch.batch_api_client import parse_results_jsonl
from pg_llm_batch.orchestrator import PostgresBatchOrchestrator
from pg_llm_batch import config as _config
from pg_llm_batch.token_counter import BatchAccumulator

_CHAT_URL = "/v1/chat/completions"
_EMBED_URL = "/v1/embeddings"


# --------------------------------------------------------------------------- #
# Small helper to slice arbitrary bytes into a few string fields.
# --------------------------------------------------------------------------- #
def _split_fields(data: bytes, n: int) -> List[str]:
    """Split ``data`` into ``n`` strings on NUL boundaries.

    Decodes with ``errors="replace"`` so we explore the full space of *valid*
    Unicode scalar strings (control chars, emoji, RTL marks, ...) — which is
    exactly what the real trust boundaries deliver: Postgres ``text`` columns
    and aiohttp-decoded HTTP bodies never contain lone surrogates, so injecting
    them would only manufacture crashes that cannot occur in production.
    """
    parts = data.split(b"\x00")
    while len(parts) < n:
        parts.append(b"")
    fields = []
    for chunk in parts[:n]:
        fields.append(chunk.decode("utf-8", errors="replace"))
    return fields


# --------------------------------------------------------------------------- #
# Target 1 — JSONL request-line assembler.
# The core of "batch assembly": turn a request tuple into an OpenAI-compatible
# JSONL line. Must never crash and must always emit serialisable, well-formed
# request objects.
# --------------------------------------------------------------------------- #
def fuzz_build_json_entry(data: bytes) -> None:
    request_id, model_name, raw_mode, system_prompt, user_prompt = _split_fields(data, 5)
    # Bias ~half of inputs toward the "embedding" branch, the rest to chat.
    mode = "embedding" if (data[:1] or b"c")[0] & 1 else raw_mode.lower()

    entry = PostgresBatchOrchestrator._build_json_entry(
        request_id, model_name, mode, system_prompt, user_prompt
    )

    # Structural invariants ------------------------------------------------- #
    assert isinstance(entry, dict), "entry must be a dict"
    assert entry["custom_id"] == request_id, "custom_id must round-trip the request id"
    assert entry["method"] == "POST", "method must be POST"
    assert entry["url"] in (_CHAT_URL, _EMBED_URL), f"unexpected url {entry['url']!r}"
    body = entry["body"]
    assert isinstance(body, dict) and body.get("model") == model_name

    if mode == "embedding":
        assert entry["url"] == _EMBED_URL
        assert "input" in body
        assert "messages" not in body
    else:
        assert entry["url"] == _CHAT_URL
        messages = body["messages"]
        assert isinstance(messages, list) and len(messages) >= 1
        # The user turn is always present and always last.
        assert messages[-1]["role"] == "user"
        # A system turn appears iff a non-empty system prompt was supplied.
        has_system = any(m["role"] == "system" for m in messages)
        assert has_system == bool(system_prompt)

    # The whole point of the assembler: the entry must be JSON-serialisable and
    # round-trip byte-for-byte through the same dumps() the orchestrator uses.
    dumped = json.dumps(entry, ensure_ascii=False)
    assert json.loads(dumped) == entry, "assembled entry must round-trip through JSON"


# --------------------------------------------------------------------------- #
# Target 2 — Batch API result decoder (untrusted gateway output).
# Arbitrary downloaded text must only ever fail as JSONDecodeError; anything
# else (TypeError, AttributeError, ...) is a bug.
# --------------------------------------------------------------------------- #
def fuzz_parse_results_jsonl(data: bytes) -> None:
    content = data.decode("utf-8", errors="replace")
    try:
        result = parse_results_jsonl(content)
    except json.JSONDecodeError:
        return  # documented / handled failure mode for a malformed line
    except RecursionError:
        return  # deeply-nested JSON is a CPython stdlib limit, not our bug

    assert isinstance(result, list), "parse must yield a list"
    expected = [line for line in content.strip().split("\n") if line]
    assert len(result) == len(expected), "one record per non-empty line"


def fuzz_parse_results_structured(data: bytes) -> None:
    """Feed *valid* JSONL assembled from the fuzz bytes to exercise the happy
    path and the record-count invariant with well-formed input."""
    fields = _split_fields(data, 4)
    lines = [json.dumps({"custom_id": f, "n": i}) for i, f in enumerate(fields) if f]
    content = "\n".join(lines)
    result = parse_results_jsonl(content)
    assert isinstance(result, list)
    assert len(result) == len(lines)
    for original, decoded in zip(lines, result):
        assert json.loads(original) == decoded


# --------------------------------------------------------------------------- #
# Target 3 — Postgres KV config (de)serialiser.
# _split_full_key and _deserialize_value read values written by (potentially
# older / hand-edited) rows in the com_config table. They must never raise.
# --------------------------------------------------------------------------- #
def fuzz_config_roundtrip(data: bytes) -> None:
    full_key, raw = _split_fields(data, 2)

    # _split_full_key: total, never raises, always a 2-tuple of str.
    category, key = _config._split_full_key(full_key)
    assert isinstance(category, str) and isinstance(key, str)
    if "." not in full_key:
        assert category == "global" and key == full_key

    # _deserialize_value: fully guarded, must not raise for any (key, raw).
    value = _config._deserialize_value(full_key, raw)
    # For a bool-typed known key the result must be a real bool.
    item = _config.DEFAULT_CONFIG_INDEX.get(full_key)
    if item is not None and item["type"] is bool:
        assert isinstance(value, bool)

    # Serialise -> deserialise round-trip for every known default value must be
    # type-stable and value-preserving.
    for known_key, meta in _config.DEFAULT_CONFIG_INDEX.items():
        original = meta["value"]
        restored = _config._deserialize_value(known_key, _config._serialize_value(original))
        assert restored == original, f"round-trip changed {known_key}: {original!r} -> {restored!r}"
        assert type(restored) is type(original), f"round-trip changed type of {known_key}"


# --------------------------------------------------------------------------- #
# Target 4 — BatchAccumulator byte accounting.
# compute_byte_size sizes each JSONL line for the byte-bounded file limit; it
# must never crash and must match the real UTF-8 byte length (+1 for newline).
# --------------------------------------------------------------------------- #
def fuzz_byte_accounting(data: bytes) -> None:
    (line,) = _split_fields(data, 1)
    size = BatchAccumulator.compute_byte_size(line)
    assert isinstance(size, int)
    assert size == len(line.encode("utf-8")) + 1
    assert size >= 1  # always at least the trailing newline
