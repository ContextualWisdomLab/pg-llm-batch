#!/usr/bin/env bash
set -euo pipefail

container="${1:?PostgreSQL container name is required}"

# Reuse the already-initialized image instance. The separately built component
# image supplies the installed package and locked Psycopg runtime. Sharing the
# PostgreSQL container network namespace keeps the database unexposed on the
# runner while the probe executes the real ANY(%s) catalog query.
docker run --rm \
  --network "container:${container}" \
  --volume "${PWD}/tests:/tests:ro" \
  pg-llm-batch:ci \
  python /tests/smoke_restore_catalog_index_semantics.py
