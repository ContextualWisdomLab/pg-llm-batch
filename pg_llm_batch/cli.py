# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Standalone command-line interface: ``python -m pg_llm_batch ...``.

Subcommands:
    init-db        apply the batch schema (idempotent)
    config set     set a KV config value
    config get     read a KV config value
    config set-secret   store a secret from no-echo TTY input or stdin
    count-tokens   count bounded UTF-8 text from stdin via pg_tiktoken
    submit         upload a prepared batch payload and create a batch job
    poll           poll a batch job's status once
    wait           poll until a batch reaches a terminal state
    retrieve       download completed batch results
    cancel         cancel a provider batch job
    health         print the readiness report (exit 0 ready / 1 not)
    serve-healthz  serve GET /healthz

The DSN is resolved from --dsn or the PG_LLM_BATCH_DSN bootstrap env var only.
Command-line DSNs may select a database but may not carry password/private-key
credentials; use standard libpq secret mechanisms outside process argv. All
other config/secrets come from the database KV stores. Secret plaintext and
count-tokens prompt content are never accepted as command-line arguments.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import re
import sys
import warnings
from contextlib import ExitStack
from typing import List, Optional

from psycopg import ProgrammingError
from psycopg.conninfo import conninfo_to_dict

from . import db
from .batch_api_client import BatchAPIClient, config_credentials_provider
from .bootstrap import resolve_dsn, resolve_secret_key
from .config import PostgresConfigStore, SecretStore
from .exceptions import ConfigError, PgLlmBatchError
from .health import check_health, serve_healthz
from .token_counter import TokenCounter

MAX_SECRET_INPUT_CHARACTERS = 65_536
MAX_TOKEN_INPUT_BYTES = 1_048_576
SECRET_LINE_SEPARATORS = frozenset("\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029")
CLI_DSN_SENSITIVE_PARAMETERS = frozenset(
    {
        "password",
        "passfile",
        "sslkey",
        "sslpassword",
        "oauth_client_secret",
    }
)


class _RedactingArgumentParser(argparse.ArgumentParser):
    """Argument parser that does not reflect arbitrary rejected argv values."""

    def error(self, message: str) -> None:
        """Exit with a parser error after redacting unrecognized argv values."""
        redacted_message = re.sub(
            r"(?s)^unrecognized arguments:.*$",
            "unrecognized arguments: <redacted>",
            message,
        )
        super().error(redacted_message)


def _validate_cli_dsn(value: str) -> str:
    """Accept valid libpq selectors while refusing credential-bearing argv data."""
    try:
        parameters = conninfo_to_dict(value)
    except ProgrammingError:
        raise argparse.ArgumentTypeError(
            "Postgres DSN must be valid libpq connection information"
        ) from None
    if CLI_DSN_SENSITIVE_PARAMETERS.intersection(parameters):
        raise argparse.ArgumentTypeError(
            "Credential-bearing Postgres DSNs are not accepted in --dsn; "
            "use libpq secret mechanisms outside process argv"
        )
    return value


def _add_common(parser: argparse.ArgumentParser) -> None:
    """Add the shared credential-free ``--dsn`` selector to a subcommand parser."""
    parser.add_argument(
        "--dsn",
        default=None,
        type=_validate_cli_dsn,
        help=(
            "Credential-free Postgres selector "
            "(else PG_LLM_BATCH_DSN bootstrap env var)"
        ),
    )


def _close_if_supported(resource: object) -> None:
    """Close one owned collaborator when it exposes a synchronous close hook."""
    close = getattr(resource, "close", None)
    if callable(close):
        close()


def _validate_secret_input(value: str) -> str:
    """Require one non-empty bounded logical line of secret input."""
    if not value:
        raise ConfigError("Secret value must not be empty")
    if len(value) > MAX_SECRET_INPUT_CHARACTERS:
        raise ConfigError(
            f"Secret value must not exceed {MAX_SECRET_INPUT_CHARACTERS} characters"
        )
    if any(separator in value for separator in SECRET_LINE_SEPARATORS):
        raise ConfigError("Secret value must be a single line")
    return value


def _read_secret_input() -> str:
    """Read one bounded secret from a no-echo TTY prompt or standard input.

    Interactive terminals use :func:`getpass.getpass` and fail closed if the
    runtime cannot disable terminal echo. Non-interactive callers may pipe
    exactly one logical line on standard input; one trailing LF or CRLF line
    ending is removed. Other logical line separators remain data until the
    validator rejects them. Secret plaintext is never accepted through process
    arguments.
    """
    is_tty = getattr(sys.stdin, "isatty", None)
    if callable(is_tty) and is_tty():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                secret_value = getpass.getpass("Secret value: ")
        except getpass.GetPassWarning:
            raise ConfigError(
                "Echo-free interactive secret input is unavailable"
            ) from None
        return _validate_secret_input(secret_value)

    raw = sys.stdin.read(MAX_SECRET_INPUT_CHARACTERS + 3)
    if raw.endswith("\r\n"):
        raw = raw[:-2]
    elif raw.endswith("\n"):
        raw = raw[:-1]
    return _validate_secret_input(raw)


def _read_token_input() -> str:
    """Read bounded UTF-8 token-counting content from standard input.

    The byte ceiling is enforced before configuration-store construction or
    PostgreSQL tokenization. Unlike secret-line input, token content preserves
    every decoded character including trailing newline characters because those
    characters can affect the authoritative pg_tiktoken count.

    Returns:
        The exact UTF-8 text supplied through standard input.

    Raises:
        ConfigError: If the input exceeds :data:`MAX_TOKEN_INPUT_BYTES` or is
            not valid UTF-8.
    """
    binary_stream = getattr(sys.stdin, "buffer", None)
    if binary_stream is not None:
        raw = binary_stream.read(MAX_TOKEN_INPUT_BYTES + 1)
    else:
        text = sys.stdin.read(MAX_TOKEN_INPUT_BYTES + 1)
        try:
            raw = text.encode("utf-8")
        except UnicodeEncodeError:
            raise ConfigError("Token input must be valid UTF-8") from None
    if len(raw) > MAX_TOKEN_INPUT_BYTES:
        raise ConfigError(
            f"Token input exceeds byte limit ({MAX_TOKEN_INPUT_BYTES} bytes)"
        )
    try:
        return bytes(raw).decode("utf-8")
    except UnicodeDecodeError:
        raise ConfigError("Token input must be valid UTF-8") from None


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser and all supported subcommands."""
    parser = _RedactingArgumentParser(
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
    p_secret = cfg_sub.add_parser(
        "set-secret",
        help="Store a secret from a no-echo prompt or standard input",
    )
    _add_common(p_secret)
    p_secret.add_argument("secret_key")

    p_count = sub.add_parser(
        "count-tokens",
        help="Count bounded UTF-8 stdin content without exposing it in argv",
    )
    _add_common(p_count)
    p_count.add_argument("--model", required=True)
    p_count.add_argument(
        "--stdin",
        action="store_true",
        required=True,
        help="Read exact UTF-8 prompt content from standard input",
    )

    p_submit = sub.add_parser("submit", help="Upload payload + create batch job")
    _add_common(p_submit)
    p_submit.add_argument("--endpoint", required=True, help="Endpoint alias")
    p_submit.add_argument("--file-path", required=True, help="memory://<file_id>")
    p_submit.add_argument("--batch-endpoint", default="/v1/chat/completions")

    p_poll = sub.add_parser("poll", help="Poll a batch job status once")
    _add_common(p_poll)
    p_poll.add_argument("--endpoint", required=True)
    p_poll.add_argument("--batch-id", required=True)

    p_wait = sub.add_parser("wait", help="Wait for a terminal batch status")
    _add_common(p_wait)
    p_wait.add_argument("--endpoint", required=True)
    p_wait.add_argument("--batch-id", required=True)
    p_wait.add_argument("--poll-interval", type=float, default=5.0)
    p_wait.add_argument("--timeout", type=float, default=3600.0)

    p_retrieve = sub.add_parser("retrieve", help="Download batch results")
    _add_common(p_retrieve)
    p_retrieve.add_argument("--endpoint", required=True)
    p_retrieve.add_argument("--batch-id", required=True)

    p_cancel = sub.add_parser("cancel", help="Cancel a provider batch job")
    _add_common(p_cancel)
    p_cancel.add_argument("--endpoint", required=True)
    p_cancel.add_argument("--batch-id", required=True)

    p_health = sub.add_parser("health", help="Print readiness report")
    _add_common(p_health)

    p_serve = sub.add_parser("serve-healthz", help="Serve GET /healthz")
    _add_common(p_serve)
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8080)

    return parser


def _make_client(dsn: str) -> BatchAPIClient:
    """Assemble a client and retain its CLI-owned credential-store resources."""
    with ExitStack() as cleanup:
        config = PostgresConfigStore(dsn)
        cleanup.callback(_close_if_supported, config)
        secrets = SecretStore(dsn, fernet_key=resolve_secret_key())
        cleanup.callback(_close_if_supported, secrets)
        provider = config_credentials_provider(config, secrets)
        client = BatchAPIClient(dsn, provider)
        setattr(client, "_pg_llm_batch_cli_config_store", config)
        setattr(client, "_pg_llm_batch_cli_secret_store", secrets)
        cleanup.pop_all()
    return client


def _close_client_resources(client: object) -> None:
    """Release CLI-owned credential stores after the HTTP client closes."""
    secret_store = getattr(client, "_pg_llm_batch_cli_secret_store", None)
    config_store = getattr(client, "_pg_llm_batch_cli_config_store", None)
    _close_if_supported(secret_store)
    _close_if_supported(config_store)


def main(argv: Optional[List[str]] = None) -> int:
    """Run the command-line entry point and map domain errors to exit code 2."""
    try:
        return _dispatch(argv)
    except PgLlmBatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _dispatch(argv: Optional[List[str]]) -> int:
    """Parse arguments, resolve the DSN, and run the selected subcommand."""
    args = build_parser().parse_args(argv)
    dsn = resolve_dsn(getattr(args, "dsn", None))

    if args.command == "init-db":
        db.apply_schema(dsn)
        print("Schema applied.")
        return 0

    if args.command == "config":
        if args.config_command == "set":
            store = PostgresConfigStore(dsn)
            try:
                store.set(args.category, args.key, args.value)
                print(f"Set {args.category}.{args.key}")
                return 0
            finally:
                _close_if_supported(store)
        if args.config_command == "get":
            store = PostgresConfigStore(dsn)
            try:
                print(store.get(args.category, args.key))
                return 0
            finally:
                _close_if_supported(store)
        if args.config_command == "set-secret":  # pragma: no branch - exhaustive parser
            secret_value = _read_secret_input()
            secrets = SecretStore(dsn, fernet_key=resolve_secret_key())
            try:
                secrets.set_secret(args.secret_key, secret_value)
                print("Secret stored.")
                return 0
            finally:
                _close_if_supported(secrets)

    if args.command == "count-tokens":
        token_input = _read_token_input()
        config = PostgresConfigStore(dsn)
        try:
            counter = TokenCounter(dsn, config=config)
            try:
                tokens = counter.count_tokens(token_input, args.model)
                print(json.dumps({"model": args.model, "tokens": tokens}))
                return 0
            finally:
                _close_if_supported(counter)
        finally:
            _close_if_supported(config)

    if args.command == "submit":
        return _run_submit(dsn, args)

    if args.command == "poll":
        return _run_async_report(
            dsn, lambda c: c.get_batch_status(args.batch_id, args.endpoint)
        )

    if args.command == "wait":
        return _run_async_report(
            dsn,
            lambda c: c.wait_for_batch(
                args.batch_id,
                args.endpoint,
                poll_interval_seconds=args.poll_interval,
                timeout_seconds=args.timeout,
            ),
        )

    if args.command == "retrieve":
        return _run_async_report(
            dsn, lambda c: c.download_results(args.batch_id, args.endpoint)
        )

    if args.command == "cancel":
        return _run_async_report(
            dsn, lambda c: c.cancel_batch(args.batch_id, args.endpoint)
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
    """Upload the payload, create a batch job, and print the combined result."""

    async def _go() -> int:
        """Run the upload-and-create coroutine within a client context."""
        client = _make_client(dsn)
        try:
            async with client as active_client:
                uploaded = await active_client.upload_jsonl(
                    args.file_path, args.endpoint
                )
                job = await active_client.create_batch_job(
                    uploaded["id"], args.endpoint, endpoint=args.batch_endpoint
                )
                print(json.dumps({"file": uploaded, "batch": job}, indent=2))
            return 0
        finally:
            _close_client_resources(client)

    return asyncio.run(_go())


def _run_async_report(dsn: str, coro_factory) -> int:
    """Run a client coroutine built by ``coro_factory`` and print its JSON result."""

    async def _go() -> int:
        """Execute the coroutine within a client context and print its result."""
        client = _make_client(dsn)
        try:
            async with client as active_client:
                result = await coro_factory(active_client)
                print(json.dumps(result, indent=2, default=str))
            return 0
        finally:
            _close_client_resources(client)

    return asyncio.run(_go())


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
