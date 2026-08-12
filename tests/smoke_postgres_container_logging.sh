#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
container="pg-llm-batch-log-smoke-${GITHUB_RUN_ID:-local}-$$"
profile="/etc/postgresql/postgresql.conf.custom"
sentinel="pg_llm_batch_container_log_smoke"

cleanup() {
  docker rm --force "${container}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Exercise the reviewed operator-applied profile explicitly. The production
# image intentionally does not make this optional profile an ambient default.
docker run --detach \
  --name "${container}" \
  --env POSTGRES_HOST_AUTH_METHOD=trust \
  "${image}" \
  postgres -c "config_file=${profile}" >/dev/null

ready=0
for _ in $(seq 1 60); do
  if docker exec "${container}" pg_isready -h 127.0.0.1 -U postgres -d postgres \
      >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "${ready}" != "1" ]]; then
  docker logs "${container}" >&2 || true
  echo "PostgreSQL did not become ready with the reviewed logging profile" >&2
  exit 1
fi

test "$(docker exec "${container}" psql -h 127.0.0.1 -U postgres -d postgres -Atqc \
  "SHOW config_file")" = "${profile}"
test "$(docker exec "${container}" psql -h 127.0.0.1 -U postgres -d postgres -Atqc \
  "SHOW logging_collector")" = "off"
test "$(docker exec "${container}" psql -h 127.0.0.1 -U postgres -d postgres -Atqc \
  "SHOW log_destination")" = "stderr"
test "$(docker exec "${container}" psql -h 127.0.0.1 -U postgres -d postgres -Atqc \
  "SELECT pg_current_logfile() IS NULL")" = "t"

# A fixed non-sensitive record proves server stderr reaches the container log
# stream. docker exec output alone would not prove this runtime ownership path.
docker exec "${container}" psql -h 127.0.0.1 -U postgres -d postgres \
  -v ON_ERROR_STOP=1 -c \
  "DO \$\$ BEGIN RAISE WARNING '${sentinel}'; END \$\$;" >/dev/null 2>&1

observed=0
for _ in $(seq 1 20); do
  if docker logs "${container}" 2>&1 | grep -Fq "${sentinel}"; then
    observed=1
    break
  fi
  sleep 1
done
if [[ "${observed}" != "1" ]]; then
  docker logs "${container}" >&2 || true
  echo "PostgreSQL operational record did not reach docker logs" >&2
  exit 1
fi
