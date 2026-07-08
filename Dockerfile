# SPDX-License-Identifier: Apache-2.0
# pg-llm-batch component image: CLI + /healthz server.
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY pg_llm_batch ./pg_llm_batch
RUN pip install --no-cache-dir .

# Bootstrap transport only: DSN + optional Fernet key are injected as env.
ENV PG_LLM_BATCH_DSN="" \
    PG_LLM_BATCH_HEALTH_PORT=8080

EXPOSE 8080

# Container health command hits the same readiness path /healthz serves.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS "http://localhost:${PG_LLM_BATCH_HEALTH_PORT}/healthz" || exit 1

CMD ["sh", "-c", "python -m pg_llm_batch serve-healthz --port ${PG_LLM_BATCH_HEALTH_PORT}"]
