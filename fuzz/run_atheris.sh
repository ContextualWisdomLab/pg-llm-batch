#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Run every Atheris harness for a bounded time budget, seeded from its corpus.
#
#   fuzz/run_atheris.sh [MAX_SECONDS]
#
# MAX_SECONDS defaults to 60 (per target) — short enough for a PR gate.
# Requires Atheris (CPython 3.9–3.12); on newer interpreters this exits 0 with a
# note, because the same oracles are covered by the Hypothesis suite.
set -euo pipefail

MAX_SECONDS="${1:-60}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"
cd "${ROOT}"

if ! python -c "import atheris" 2>/dev/null; then
  echo "atheris not importable on this interpreter — skipping coverage-guided run."
  echo "(the Hypothesis property suite in tests/fuzz/ covers the same oracles.)"
  exit 0
fi

declare -a HARNESSES=(
  "fuzz_build_json_entry"
  "fuzz_parse_results"
  "fuzz_config_roundtrip"
  "fuzz_byte_accounting"
)

status=0
for h in "${HARNESSES[@]}"; do
  corpus="fuzz/corpus/${h#fuzz_}"
  echo "=== ${h} (max ${MAX_SECONDS}s, corpus=${corpus}) ==="
  # -max_total_time bounds wall-clock; -artifact_prefix keeps any crash file local.
  if ! python "fuzz/${h}.py" \
        -max_total_time="${MAX_SECONDS}" \
        -artifact_prefix="fuzz/crashes/${h}-" \
        "${corpus}"; then
    echo "!!! ${h} reported a crash"
    status=1
  fi
done

exit "${status}"
