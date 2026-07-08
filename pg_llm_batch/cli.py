# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Standalone command-line interface: ``python -m pg_llm_batch ...``.

Subcommands:
    init-db        apply the batch schema (idempotent)
    config set     set a KV config value
    config get     read a KV config value
    config set-secret   store a secret (Fernet-encrypted when a key is present)
    count-tokens   count tokens for text via pg_tiktoken
    submit         upload a prepared batch payload and create a batch job
    poll           poll a batch job's status
    retrieve       download completed batch results
    health         print the readiness report (exit 0 ready / 1 not)
    serve-healthz  serve GET /healthz

The DSN is resolved from --dsn or the PG_LLM_BATCH_DSN bootstrap env var only.
All other config/secrets come from the database KV stores.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import List, Optional

from . import db
from .batch_api_client import BatchAPIClient, config_credentials_provider
from .bootstrap import resolve_dsn, resolve_secret_key
from .config import PostgresConfigStore, SecretStore
from .exceptions import PgLlmBatchError
from .health import check_health, serve_healthz
from .token_counter import TokenCounter


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dsn",
        default=None,
        help="Postgres DSN (else PG_LLM_BATCH_DSN bootstrap env var)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pg_llm_batch",
        description="Standalone Postgres LLM batch engine",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-db", help="Apply batch schema (idempotent)")
    _add_common(p_init)

    p_cfg = sub.add_parser("config", help="Manage KV config and secrets")
    cfg_sub = p_cfg.add_subparsers(dest="config_command", required=True)
    p_set = cfg_sub.add_parser("set", help="Set a config value")
    _add_common(p_set)
    p_set.add_argument("category")
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_get = cfg_sub.add_parser("get", help="Get a config value")
    _add_common(p_get)
    p_get.add_argument("category")
    p_get.add_argument("key")
    p_secret = cfg_sub.add_parser("set-secret", help="Store a secret")
    _add_common(p_secret)
    p_secret.add_argument("secret_key")
    p_secret.add_argument("secret_value")

    p_count = sub.add_parser("count-tokens", help="Count tokens for text")
    _add_common(p_count)
    p_count.add_argument("--model", required=True)
    p_count.add_argument("--text", required=True)

    p_submit = sub.add_parser("submit", help="Upload payload + create batch job")
    _add_common(p_submit)
    p_submit.add_argument("--endpoint", required=True, help="Endpoint alias")
    p_submit.add_argument("--file-path", required=True, help="memory://<file_id>")
    p_submit.add_argument("--batch-endpoint", default="/v1/chat/completions")

    p_poll = sub.add_parser("poll", help="Poll a batch job status")
    _add_common(p_poll)
    p_poll.add_argument("--endpoint", required=True)
    p_poll.add_argument("--batch-id", required=True)

    p_retrieve = sub.add_parser("retrieve", help="Download batch results")
    _add_common(p_retrieve)
    p_retrieve.add_argument("--endpoint", required=True)
    p_retrieve.add_argument("--batch-id", required=True)

    p_health = sub.add_parser("health", help="Print readiness report")
    _add_common(p_health)

    p_serve = sub.add_parser("serve-healthz", help="Serve GET /healthz")
    _add_common(p_serve)
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8080)

    return parser


def _make_client(dsn: str) -> BatchAPIClient:
    config = PostgresConfigStore(dsn)
    secrets = SecretStore(dsn, fernet_key=resolve_secret_key())
    provider = config_credentials_provider(config, secrets)
    return BatchAPIClient(dsn, provider)


def main(argv: Optional[List[str]] = None) -> int:
    try:
        return _dispatch(argv)
    except PgLlmBatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _dispatch(argv: Optional[List[str]]) -> int:
    args = build_parser().parse_args(argv)
    dsn = resolve_dsn(getattr(args, "dsn", None))

    if args.command == "init-db":
        db.apply_schema(dsn)
        print("Schema applied.")
        return 0

    if args.command == "config":
        if args.config_command == "set":
            store = PostgresConfigStore(dsn)
            store.set(args.category, args.key, args.value)
            print(f"Set {args.category}.{args.key}")
            return 0
        if args.config_command == "get":
            store = PostgresConfigStore(dsn)
            print(store.get(args.category, args.key))
            return 0
        if args.config_command == "set-secret":
            secrets = SecretStore(dsn, fernet_key=resolve_secret_key())
            secrets.set_secret(args.secret_key, args.secret_value)
            print(f"Stored secret {args.secret_key}")
            return 0

    if args.command == "count-tokens":
        counter = TokenCounter(dsn, config=PostgresConfigStore(dsn))
        tokens = counter.count_tokens(args.text, args.model)
        print(json.dumps({"model": args.model, "tokens": tokens}))
        return 0

    if args.command == "submit":
        return _run_submit(dsn, args)

    if args.command == "poll":
        return _run_async_report(
            dsn, lambda c: c.get_batch_status(args.batch_id, args.endpoint)
        )

    if args.command == "retrieve":
        return _run_async_report(
            dsn, lambda c: c.download_results(args.batch_id, args.endpoint)
        )

    if args.command == "health":
        report = check_health(dsn)
        print(json.dumps(report, indent=2))
        return 0 if report["ready"] else 1

    if args.command == "serve-healthz":
        serve_healthz(dsn, host=args.host, port=args.port)
        return 0

    return 2


def _run_submit(dsn: str, args: argparse.Namespace) -> int:
    async def _go() -> int:
        async with _make_client(dsn) as client:
            uploaded = await client.upload_jsonl(args.file_path, args.endpoint)
            job = await client.create_batch_job(
                uploaded["id"], args.endpoint, endpoint=args.batch_endpoint
            )
            print(json.dumps({"file": uploaded, "batch": job}, indent=2))
        return 0

    return asyncio.run(_go())


def _run_async_report(dsn: str, coro_factory) -> int:
    async def _go() -> int:
        async with _make_client(dsn) as client:
            result = await coro_factory(client)
            print(json.dumps(result, indent=2, default=str))
        return 0

    return asyncio.run(_go())


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
