# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Fuzz harnesses for pg-llm-batch.

The untrusted-input surfaces that matter for this component are all *parsing /
assembling* boundaries:

* the JSONL **request-line assembler** (``PostgresBatchOrchestrator._build_json_entry``),
* the Batch API **result decoder** (``batch_api_client.parse_results_jsonl``),
* the Postgres KV **config (de)serializer** (``config._serialize_value`` /
  ``_deserialize_value`` / ``_split_full_key``),
* the ``BatchAccumulator`` **byte accounting** used to size JSONL files.

``fuzz.targets`` holds one pure ``fuzz_*`` function per surface. Each takes raw
``bytes``, drives the real production code, and asserts invariants — so the same
target can be replayed by:

* **Hypothesis** property tests (``tests/fuzz/``) — the CI default, pure-Python,
  runs on every supported interpreter; and
* **Atheris** coverage-guided harnesses (``fuzz/fuzz_*.py``) — optional, run only
  where Atheris supports the interpreter (CPython 3.9–3.12).
"""
