# SPDX-License-Identifier: Apache-2.0
# pg-llm-batch component image: CLI + /healthz server.
FROM ghcr.io/astral-sh/uv:0.11.19@sha256:b46b03ddfcfbf8f547af7e9eaefdf8a39c8cebcba7c98858d3162bd28cf536f6 AS uv

FROM python:3.14-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1 AS builder

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY pg_llm_batch ./pg_llm_batch
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1

WORKDIR /app

RUN apt-get update && apt-get upgrade -y && \
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
