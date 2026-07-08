# SPDX-License-Identifier: Apache-2.0
# PostgreSQL image with pg_tiktoken + pg_cron + http for pg-llm-batch.
ARG PG_MAJOR=16
FROM postgres:${PG_MAJOR}-bullseye

ARG PG_TIKTOKEN_REPO=https://github.com/postgresml/pg_tiktoken.git
ARG PG_TIKTOKEN_BRANCH=main
# Default off so a plain `docker build docker/postgres` (the context the central
# coverage-evidence job uses for each changed Dockerfile) stays fast and offline;
# docker-compose overrides ENABLE_TIKTOKEN=1 to build the tokenizer extension.
ARG ENABLE_TIKTOKEN=0

ENV DEBIAN_FRONTEND=noninteractive
ENV ENABLE_TIKTOKEN=${ENABLE_TIKTOKEN}

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential ca-certificates clang libclang-dev cmake curl git \
      libssl-dev zlib1g-dev make pkg-config \
      postgresql-server-dev-${PG_MAJOR} \
      postgresql-${PG_MAJOR}-cron \
      postgresql-${PG_MAJOR}-http && \
    rm -rf /var/lib/apt/lists/*

# COPY sources are relative to this Dockerfile's directory so the image builds
# with `docker/postgres` as the build context (compose sets context: docker/postgres).
COPY patches/ /tmp/postgres_patches/

# Build pg_tiktoken via cargo-pgrx (o200k patch applied). Failures are tolerated
# so the image still boots for pg_cron/http-only smoke tests.
RUN bash -lc 'set -euo pipefail; \
  if [ "${ENABLE_TIKTOKEN}" = "1" ]; then \
    curl https://sh.rustup.rs -sSf | bash -s -- -y --profile minimal; \
    source "$HOME/.cargo/env"; \
    cargo install --locked cargo-pgrx --version 0.16.0; \
    cargo pgrx init --pg${PG_MAJOR} /usr/lib/postgresql/${PG_MAJOR}/bin/pg_config; \
    if git clone --depth 1 --branch ${PG_TIKTOKEN_BRANCH} ${PG_TIKTOKEN_REPO} /tmp/pg_tiktoken; then \
      cd /tmp/pg_tiktoken && \
      patch -p1 < /tmp/postgres_patches/pg_tiktoken_o200k.patch && \
      cargo update -p tiktoken-rs || true && \
      (cargo pgrx install --release || echo "WARNING: pg_tiktoken build failed; continuing") && \
      rm -rf /tmp/pg_tiktoken; \
    else \
      echo "WARNING: pg_tiktoken repo unreachable; skipping"; \
    fi; \
  else \
    echo "ENABLE_TIKTOKEN=0: skipping pg_tiktoken build"; \
  fi'

COPY postgresql.conf.custom /etc/postgresql/postgresql.conf.custom

# Preload shared libraries via a wrapper entrypoint.
RUN cat <<'SCRIPT' > /usr/local/bin/pg-llm-batch-entrypoint.sh
#!/bin/bash
set -e
preload="pg_cron"
if [ "${ENABLE_TIKTOKEN:-1}" = "1" ]; then
    preload="${preload},pg_tiktoken"
fi
if [ "${1:-}" = "postgres" ]; then
    set -- "$@" -c "shared_preload_libraries=${preload}" -c "cron.database_name=postgres"
fi
exec docker-entrypoint.sh "$@"
SCRIPT
RUN chmod +x /usr/local/bin/pg-llm-batch-entrypoint.sh

ENTRYPOINT ["pg-llm-batch-entrypoint.sh"]
CMD ["postgres"]

# Init order: extensions -> schema -> cron retrieval. init/02_schema.sql is a
# build-context mirror of pg_llm_batch/schema.sql (see that file's header).
COPY init/01_extensions.sql /docker-entrypoint-initdb.d/01_extensions.sql
COPY init/02_schema.sql /docker-entrypoint-initdb.d/02_schema.sql
COPY init/03_cron_batch_retrieval.sql /docker-entrypoint-initdb.d/03_cron_batch_retrieval.sql

# Run as the unprivileged postgres user (uid 999) shipped by the base image
# rather than root (trivy DS-0002). The official entrypoint supports non-root.
USER postgres
