# SPDX-License-Identifier: Apache-2.0
# pg-llm-batch component image: CLI + /healthz server.
FROM ghcr.io/astral-sh/uv:0.12.3@sha256:2d890623d310b57771ce840f0da5eed5fc6d657da05ffaa45d82797b53fa3abc AS uv

FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6 AS builder

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
COPY pg_llm_batch ./pg_llm_batch
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6

WORKDIR /app

# Resolve runtime OS packages from one reviewed Debian snapshot. snapshot.debian.org
# maps an arbitrary timestamp to the latest import at or before that instant, so
# this fixed timestamp is a reproducible package-index identity. Valid-Until is
# disabled only for these intentionally frozen snapshot entries; security refresh
# is performed by reviewing and advancing the timestamp, not by floating builds.
RUN rm -f /etc/apt/sources.list.d/debian.sources && \
    printf '%s\n' \
      'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20260812T000000Z/ trixie main' \
      'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20260812T000000Z/ trixie-updates main' \
      'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/20260812T000000Z/ trixie-security main' \
      > /etc/apt/sources.list.d/debian-snapshot.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends libpq5 curl && \
    rm -rf /var/lib/apt/lists/* \
      /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.11 \
      /usr/local/lib/python3.11/site-packages/pip* \
      /usr/local/lib/python3.11/site-packages/setuptools* \
      /usr/local/lib/python3.11/site-packages/wheel* && \
    adduser --system --no-create-home appuser

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:${PATH}"

# Run as a non-root user (trivy DS-0002).
USER appuser

# Bootstrap transport only: DSN + optional Fernet key are injected as env.
ENV PG_LLM_BATCH_DSN="" \
    PG_LLM_BATCH_HEALTH_PORT=8080

EXPOSE 8080

# Container health command hits the same readiness path /healthz serves.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS "http://localhost:${PG_LLM_BATCH_HEALTH_PORT}/healthz" || exit 1

CMD ["sh", "-c", "python -m pg_llm_batch serve-healthz --port ${PG_LLM_BATCH_HEALTH_PORT}"]
