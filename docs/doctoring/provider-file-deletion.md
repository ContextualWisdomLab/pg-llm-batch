# Provider file deletion boundary

## Status

This document describes the **active PR** provider-file deletion slice. It is not implemented on protected `main` until the owning pull request is integrated under the live repository policy.

## Purpose and authority

`BatchAPIClient.delete_file()` is an explicit, caller-authorized cleanup primitive for a provider file that was previously uploaded through the configured Files API. It reuses the package's existing gateway credential and destination authority; it does not create a cleanup scheduler, infer retention authority from provider metadata, or treat batch cancellation as permission to delete files.

The file identifier is validated before credential resolution or provider I/O. The request is a single side-effecting `DELETE /files/{file_id}` operation, so the generic client retry policy does not replay it automatically. The same finite request timeout and no-redirect boundary used by other provider operations applies.

A successful HTTP status is not sufficient evidence. The bounded JSON response must identify the exact requested file and report `deleted: true`; otherwise pg-llm-batch fails with fixed package-owned evidence. Provider response bodies and arbitrary provider error text are not copied into exported diagnostics.

## Compatibility and residual boundaries

The OpenAI Files API currently defines `DELETE /v1/files/{file_id}` and returns deletion status including the file identifier and `deleted` flag. OpenAI also documents an upload-time `expires_after` policy; files with `purpose=batch` default to 30-day expiry and the supported explicit range is 3,600 through 2,592,000 seconds. This PR implements only explicit deletion. Input-file expiration, already-deleted/not-found reconciliation policy, automatic terminal-state cleanup, durable cleanup audit, and legal-erasure policy remain separate work.

Gateways that claim OpenAI compatibility may omit optional lifecycle surfaces. A provider that rejects deletion therefore remains a bounded provider capability/reconciliation condition; pg-llm-batch does not silently reinterpret rejection as successful cleanup.

Remote deletion also does not erase package-owned historical provider file identifiers, local PostgreSQL content, logs owned by the embedding host, backups, or exports. Those stores require their own retention and data-rights authority.

## Failure and recovery

- Invalid local file identifiers fail before credential or network access.
- Provider HTTP rejection produces a fixed `ProviderHTTPError` category and is not automatically retried by this side-effecting operation.
- Malformed successful deletion evidence fails closed.
- Callers may reconcile uncertain outcomes explicitly using the provider's supported file-lifecycle surface; this slice does not claim distributed exactly-once cleanup.
- Rollback removes the explicit deletion API only; it cannot restore a provider file that has already been deleted.

## Primary reference — APA 7th

OpenAI. (2026). *Files | OpenAI API reference*. https://platform.openai.com/docs/api-reference/files
