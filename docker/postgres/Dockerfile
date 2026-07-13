# SPDX-License-Identifier: Apache-2.0
# PostgreSQL image with pg_cron + http, plus an opt-in pg_tiktoken target.
ARG PG_MAJOR=16
FROM postgres:${PG_MAJOR}-bookworm@sha256:da788743d2060767375896de4d646f7576f5911461444b372616f19ea61db2ec AS postgres-base

ARG PG_MAJOR=16
ENV DEBIAN_FRONTEND=noninteractive

# Patch the base OS and remove gosu: this image always runs as the official
# postgres user, so gosu is unreachable runtime code and its stale Go stdlib
# would otherwise leave Medium+ vulnerabilities in the final filesystem.
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
      postgresql-${PG_MAJOR}-cron \
      postgresql-${PG_MAJOR}-http && \
    rm -rf /var/lib/apt/lists/* /usr/local/bin/gosu

COPY postgresql.conf.custom /etc/postgresql/postgresql.conf.custom

# Preload shared libraries via a wrapper entrypoint.
RUN cat <<'SCRIPT' > /usr/local/bin/pg-llm-batch-entrypoint.sh
#!/bin/bash
set -e
preload="pg_cron"
if [ "${ENABLE_TIKTOKEN:-0}" = "1" ]; then
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

# Liveness probe (trivy DS-0026); compose adds a richer pg_tiktoken-aware check.
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=10 \
    CMD pg_isready -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-postgres}" || exit 1

# Init order: extensions -> schema -> cron retrieval. init/02_schema.sql is a
# build-context mirror of pg_llm_batch/schema.sql (see that file's header).
COPY init/01_extensions.sql /docker-entrypoint-initdb.d/01_extensions.sql
COPY init/02_schema.sql /docker-entrypoint-initdb.d/02_schema.sql
COPY init/03_cron_batch_retrieval.sql /docker-entrypoint-initdb.d/03_cron_batch_retrieval.sql

# Compose selects this target. Every executable input is immutable and an
# enabled tokenizer build is fail-closed, leaving the failing command visible.
FROM rust:1.97-slim-bookworm@sha256:cfbb0e0ef7a73e736386bfa346f1cb0503c6d162969dc9426fb37834f3f64c25 AS rust-toolchain

FROM postgres-base AS with-tiktoken

ARG PG_MAJOR=16
ARG PG_TIKTOKEN_COMMIT=0baf8d46620c9fa21acf4dc5f167e25f693aa932
ENV ENABLE_TIKTOKEN=1 \
    CARGO_HOME=/usr/local/cargo \
    RUSTUP_HOME=/usr/local/rustup \
    PATH="/usr/local/cargo/bin:${PATH}"

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential ca-certificates clang libclang-dev cmake git \
      libssl-dev zlib1g-dev make pkg-config \
      postgresql-server-dev-${PG_MAJOR} && \
    rm -rf /var/lib/apt/lists/*

COPY --from=rust-toolchain /usr/local/cargo /usr/local/cargo
COPY --from=rust-toolchain /usr/local/rustup /usr/local/rustup
COPY patches/ /tmp/postgres_patches/

RUN bash -c 'set -euxo pipefail; \
  command -v cargo; \
  cargo --version; \
  rustc --version; \
  cargo install --locked cargo-pgrx --version 0.16.1; \
  cargo pgrx init --pg${PG_MAJOR} /usr/lib/postgresql/${PG_MAJOR}/bin/pg_config; \
  git init /tmp/pg_tiktoken; \
  cd /tmp/pg_tiktoken; \
  git remote add origin https://github.com/kelvich/pg_tiktoken.git; \
  git fetch --depth 1 origin "${PG_TIKTOKEN_COMMIT}"; \
  git checkout --detach FETCH_HEAD; \
  test "$(git rev-parse HEAD)" = "${PG_TIKTOKEN_COMMIT}"; \
  patch -p1 < /tmp/postgres_patches/pg_tiktoken_o200k.patch; \
  cargo generate-lockfile; \
  cargo fetch --locked; \
  cargo pgrx install --release; \
  rm -rf /tmp/pg_tiktoken /tmp/postgres_patches \
    /usr/local/cargo /usr/local/rustup; \
  apt-get purge -y --auto-remove \
    build-essential clang libclang-dev cmake git libssl-dev zlib1g-dev make \
    pkg-config postgresql-server-dev-${PG_MAJOR}; \
  rm -rf /var/lib/apt/lists/*'

USER postgres

# Default/central-check target: no Rust toolchain is pulled and the log-visible
# environment makes the deliberate tokenizer omission explicit.
FROM postgres-base AS runtime

ENV ENABLE_TIKTOKEN=0
USER postgres
