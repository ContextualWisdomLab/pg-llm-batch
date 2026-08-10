# SPDX-License-Identifier: Apache-2.0
# pg-llm-batch component image: CLI + /healthz server.
FROM ghcr.io/astral-sh/uv:0.12.0@sha256:606e70c71c852d03f611b1e56a195d08648507018a7057fab82c4974c4eae105 AS uv

FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6 AS builder

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY pg_llm_batch ./pg_llm_batch
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6

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

# Bootstrap transport only: the DSN is injected as env. The health listener uses
# the image's fixed exposed port by default; deployments that need another port
# must override the executable command explicitly rather than shell-expanding env.
ENV PG_LLM_BATCH_DSN=""

EXPOSE 8080

# Container health command hits the same readiness path /healthz serves without a
# shell boundary, so environment text cannot become executable command syntax.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["curl", "-fsS", "http://localhost:8080/healthz"]

CMD ["python", "-m", "pg_llm_batch", "serve-healthz", "--host", "0.0.0.0", "--port", "8080"]
