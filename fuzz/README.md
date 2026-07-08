# Fuzzing pg-llm-batch

This component's real risk lives at its **parsing and assembly boundaries** —
the points where arbitrary, externally-influenced bytes get turned into
structured objects. A malformed model name, a hand-edited config row, or a
Batch API result payload from a flaky gateway must never crash the batch
pipeline or silently corrupt a JSONL request line.

We fuzz those boundaries two ways, sharing **one oracle** (`fuzz/targets.py`):

| Engine | License | Where it runs | How |
| ------ | ------- | ------------- | --- |
| **Hypothesis** | MPL-2.0 | Every interpreter, default `pytest` run | `tests/fuzz/test_fuzz_properties.py` |
| **Atheris** (libFuzzer) | Apache-2.0 | CPython 3.9–3.12, coverage-guided campaigns | `fuzz/fuzz_*.py` |

Both are permissive (no GPL/AGPL). Atheris only publishes wheels through
CPython 3.12; on newer interpreters the Hypothesis suite covers the identical
oracles, so nothing is lost.

## Targets (CodeGraph-selected untrusted-input surfaces)

The surfaces were found with CodeGraph (`codegraph explore "…parse decode
serialize deserialize validate untrusted input"` and follow-ups over the
orchestrator / client / config), then ranked by trust-boundary exposure:

1. **`fuzz_build_json_entry`** — `PostgresBatchOrchestrator._build_json_entry`,
   the JSONL **request-line assembler**. Asserts: always a serialisable dict,
   `custom_id` round-trips, correct chat/embedding shape, system turn present
   iff a system prompt was supplied, and `json.dumps → json.loads` is identity.
2. **`fuzz_parse_results_jsonl` / `_structured`** — `batch_api_client.parse_results_jsonl`,
   the Batch API **result decoder** (untrusted gateway output). Asserts: only
   ever fails as `JSONDecodeError`, and yields exactly one record per non-empty
   line.
3. **`fuzz_config_roundtrip`** — `config._split_full_key` / `_deserialize_value`
   / `_serialize_value`, the Postgres KV **config (de)serialiser**. Asserts: the
   split is total, deserialisation never raises, and every default value
   survives a serialise→deserialise round-trip type- and value-stable.
4. **`fuzz_byte_accounting`** — `BatchAccumulator.compute_byte_size`, which sizes
   each JSONL line for the byte-bounded file limit. Asserts it equals the real
   UTF-8 byte length + 1 and is always ≥ 1.

Seed corpora live in `fuzz/corpus/<target>/`.

## Running

```bash
# Property-based suite (fast, part of the normal test run):
pip install -e ".[test]"
pytest tests/fuzz/ -q

# Coverage-guided campaigns (needs CPython ≤ 3.12):
pip install -e ".[fuzz]"
fuzz/run_atheris.sh 60          # 60s per target, seeded from the corpus
python fuzz/fuzz_build_json_entry.py -atheris_runs=500000   # single target
python fuzz/fuzz_parse_results.py fuzz/corpus/parse_results  # replay a corpus
```

Any crash is written to `fuzz/crashes/` (git-ignored) as a reproducer you can
replay by passing the file path to the harness.

## Adding a target

1. Add a pure `fuzz_<name>(data: bytes)` oracle to `fuzz/targets.py` that drives
   the real code and asserts its invariants (swallow only *documented* failure
   modes).
2. Add a thin `fuzz/fuzz_<name>.py` Atheris harness and a
   `tests/fuzz/` property test that both call it.
3. Drop a few seeds in `fuzz/corpus/<name>/`.
