# Durable provider lifecycle field contract

## Status

ACTIVE-PR. This assurance note describes the bounded validation introduced by the
current lifecycle-field change. It becomes IMPLEMENTED-ON-PROTECTED-MAIN only
after the exact source is accepted and merged through repository governance.

## Problem boundary

Provider lifecycle observations are untrusted control-plane evidence. A durable
projection must not persist arbitrary non-empty status or endpoint strings and
then infer terminal semantics from those unverified values. At the same time,
existing sparse observations remain compatible: an absent/empty status maps to
the historical `unknown` state and an absent/empty endpoint remains `None`.

The durable persistence boundary therefore validates every present non-empty
status and endpoint before PostgreSQL acquisition. Unsupported values fail with
fixed package-owned error categories and the rejected provider value is not
copied into the error message. The HTTP client's broader endpoint grammar is a
separate transport-compatibility boundary; durable evidence intentionally claims
only the first-party Batch vocabulary verified here.

## Verified vocabulary

As checked on 2026-08-13, the OpenAI Batch API reference documents Batch support
for `/v1/responses`, `/v1/chat/completions`, `/v1/embeddings`,
`/v1/completions`, and `/v1/moderations`. The lifecycle vocabulary represented
by the Batch object and cancellation flow is `validating`, `failed`,
`in_progress`, `finalizing`, `completed`, `expired`, `cancelling`, and
`cancelled`.

`completed`, `failed`, `expired`, and `cancelled` are the package's durable
terminal set. `cancelling` remains transitional and must not receive a terminal
timestamp merely because cancellation has been requested.

OpenAI-compatible providers may expose extensions, but pg-llm-batch does not
silently promote an unverified extension into durable semantics. Supporting an
additional endpoint or status requires a reviewed compatibility change and
fresh regression/provider evidence.

## Failure, rollback, and recovery

This change adds no schema migration and does not rewrite historical lifecycle
rows. Rejected new observations fail before database I/O. Rollback is therefore
a source rollback of the validation change; existing PostgreSQL state is not
transformed by that rollback.

If an embedding provider adds a legitimate new lifecycle value, operators should
not weaken validation locally. The recovery path is to verify the provider
contract, add the value to the reviewed finite set with tests and documentation,
and deploy that accepted package revision.

## Verification expectations

Acceptance requires regressions proving that unsupported, oversized,
control-bearing, and non-string present values fail before PostgreSQL access;
that sparse absence preserves the prior safe defaults; that every currently
verified endpoint/status is accepted; and that terminal timestamps are assigned
only to the reviewed terminal subset. Repository Python 3.10/3.12/3.14, exact
owned-production statement/branch coverage, docstrings, packaging, security,
SAST, PostgreSQL/container, and required central review gates remain mandatory.

## Primary reference

OpenAI. (2026). *Batch | OpenAI API reference*.
https://platform.openai.com/docs/api-reference/batch/object
