#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Atheris coverage-guided harness: Postgres KV config (de)serialiser.

    python fuzz/fuzz_config_roundtrip.py -atheris_runs=200000
    python fuzz/fuzz_config_roundtrip.py fuzz/corpus/config_roundtrip   # replay corpus

Requires Atheris (CPython 3.9–3.12). See fuzz/README.md.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import atheris

with atheris.instrument_imports():
    from fuzz.targets import fuzz_config_roundtrip


def TestOneInput(data: bytes) -> None:
    fuzz_config_roundtrip(data)


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
