#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Atheris coverage-guided harness: JSONL request-line assembler.

    python fuzz/fuzz_build_json_entry.py -atheris_runs=200000
    python fuzz/fuzz_build_json_entry.py fuzz/corpus/build_json_entry   # replay corpus

Requires Atheris (CPython 3.9–3.12). On unsupported interpreters the same oracle
runs via Hypothesis in tests/fuzz/. See fuzz/README.md.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import atheris

with atheris.instrument_imports():
    from fuzz.targets import fuzz_build_json_entry


def TestOneInput(data: bytes) -> None:
    fuzz_build_json_entry(data)


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
