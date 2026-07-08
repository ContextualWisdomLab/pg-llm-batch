# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Property-based fuzzing of pg-llm-batch parsing/assembly surfaces.

Runs the *same* oracle functions the Atheris harnesses use (``fuzz.targets``),
but driven by Hypothesis (MPL-2.0) so they execute on every supported
interpreter and inside the normal ``pytest`` run — no native fuzzing engine
required. Also replays the committed seed corpus so a crashing seed is caught
deterministically in CI.

These tests are fast by design (bounded example counts) so they can live in the
default suite; the coverage-guided, longer campaigns run via ``fuzz/``.
"""

import os
import sys

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# Make the top-level ``fuzz`` package importable regardless of pytest rootdir.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from fuzz import targets  # noqa: E402

_CORPUS_ROOT = os.path.join(_REPO_ROOT, "fuzz", "corpus")

# Each entry: (oracle callable, corpus subdirectory).
_TARGETS = [
    (targets.fuzz_build_json_entry, "build_json_entry"),
    (targets.fuzz_parse_results_jsonl, "parse_results"),
    (targets.fuzz_parse_results_structured, "parse_results"),
    (targets.fuzz_config_roundtrip, "config_roundtrip"),
    (targets.fuzz_byte_accounting, "byte_accounting"),
]

_FUZZ_SETTINGS = settings(
    max_examples=400,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# --------------------------------------------------------------------------- #
# Property tests — arbitrary bytes must never trip an invariant.
# --------------------------------------------------------------------------- #
@_FUZZ_SETTINGS
@given(st.binary(max_size=4096))
def test_build_json_entry_never_crashes(data):
    targets.fuzz_build_json_entry(data)


@_FUZZ_SETTINGS
@given(st.binary(max_size=4096))
def test_parse_results_jsonl_never_crashes(data):
    targets.fuzz_parse_results_jsonl(data)


@_FUZZ_SETTINGS
@given(st.binary(max_size=4096))
def test_parse_results_structured_roundtrips(data):
    targets.fuzz_parse_results_structured(data)


@_FUZZ_SETTINGS
@given(st.binary(max_size=2048))
def test_config_roundtrip_never_crashes(data):
    targets.fuzz_config_roundtrip(data)


@_FUZZ_SETTINGS
@given(st.binary(max_size=4096))
def test_byte_accounting_never_crashes(data):
    targets.fuzz_byte_accounting(data)


# --------------------------------------------------------------------------- #
# Deterministic seed-corpus replay — every committed seed must pass its oracle.
# --------------------------------------------------------------------------- #
def _corpus_cases():
    cases = []
    for oracle, subdir in _TARGETS:
        d = os.path.join(_CORPUS_ROOT, subdir)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            path = os.path.join(d, name)
            if os.path.isfile(path):
                cases.append(pytest.param(oracle, path, id=f"{oracle.__name__}:{name}"))
    return cases


@pytest.mark.parametrize("oracle,path", _corpus_cases())
def test_seed_corpus(oracle, path):
    with open(path, "rb") as f:
        data = f.read()
    oracle(data)
