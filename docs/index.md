---
title: pg-llm-batch
description: PostgreSQL-backed token counting, batch assembly, and durable OpenAI-compatible batch lifecycle.
---

# pg-llm-batch

pg-llm-batch is a standalone and embeddable engine for authoritative PostgreSQL token counting, bounded JSONL batch assembly, and durable interaction with OpenAI-compatible Batch APIs.

## What this repository owns

- token counts produced inside PostgreSQL through `pg_tiktoken`;
- token-, byte-, and record-bounded JSONL batch assembly;
- durable standalone and tenant-qualified batch lifecycle state;
- validated upload, polling, retrieval, retry, and provider-file lifecycle primitives;
- package-owned database, privacy, recovery, and observability contracts.

## Boundary

The package does not select providers or models, own application prompts or product-domain truth, provide identity and authorization, or claim distributed exactly-once delivery. Contextual Orchestrator retains provider discovery and routing. Embedding hosts retain authentication, tenant authorization, SDK/exporter configuration, retention policy, and caller-owned transactions.

Consumers integrate through the released package contract. They must not copy branch source, query another service's database, or treat a Draft PR as immutable release authority.

## Operability

Unknown tenant scope, incompatible metadata, oversized provider content, unbounded retry instructions, or incomplete release evidence fails closed. A branch, workflow run, package build, or SBOM alone is not a release.

## Navigate

- [Source repository](https://github.com/ContextualWisdomLab/pg-llm-batch)
- [README](https://github.com/ContextualWisdomLab/pg-llm-batch#readme)
- [Architecture](https://github.com/ContextualWisdomLab/pg-llm-batch/blob/main/ARCHITECTURE.md)
- [Remote batch lifecycle](https://github.com/ContextualWisdomLab/pg-llm-batch/blob/main/docs/remote-batch-lifecycle.md)
- [DeepWiki](https://deepwiki.com/ContextualWisdomLab/pg-llm-batch)
- [ContextualWisdomLab](https://github.com/ContextualWisdomLab)

Publication is complete only after this source reaches protected `main` and the live GitHub Pages endpoint is verified.
