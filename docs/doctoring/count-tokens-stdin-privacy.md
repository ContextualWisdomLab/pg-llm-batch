# Count-tokens stdin privacy boundary

## Maturity

**ACTIVE-PR #173.** This document describes the candidate behavior on the current
`fix/count-tokens-stdin-privacy` source. It must not be read as
IMPLEMENTED-ON-PROTECTED-MAIN until the unchanged accepted result reaches
protected `main` and its exact integrated head is reverified.

## Problem statement

Prompt content is legitimate application data and must remain semantically intact
for authoritative token counting. It can also contain PII, confidential business
text, unreleased source, incident data, or other purpose-bound material. Passing
that content as `count-tokens --text <content>` creates an avoidable secondary
copy in process invocation state before pg-llm-batch can enforce its own data
handling boundary.

MITRE CWE-214 classifies sensitive information carried in visible process
invocation elements as an information-exposure weakness. Python 3.14.6 documents
that arguments supplied to a Python program are represented in `sys.argv`; for
`python -m module ...`, arguments after the module invocation remain available to
the executed program. Therefore removing content from a later log message does
not repair the earlier argv exposure.

The remedy is **not** prompt masking. The actual token-counting operation needs
the original text. The privacy control removes an unnecessary diagnostic/process
copy while preserving purpose-bound content exactly for PostgreSQL
`pg_tiktoken`.

## Candidate contract

The candidate CLI accepts token-counting content only through an explicit
`--stdin` source:

```bash
printf '%s' 'hello world' | \
  python -m pg_llm_batch count-tokens --model gpt-4o --stdin
```

The boundary is intentionally narrow:

1. `--text` is no longer an accepted prompt-content option. Rejected legacy argv
   content is not reflected in parser diagnostics.
2. `--stdin` is explicit rather than inferred from an absent option, keeping
   content-source authority deterministic.
3. The binary stdin path reads at most `MAX_TOKEN_INPUT_BYTES + 1` bytes, where
   `MAX_TOKEN_INPUT_BYTES` is 1,048,576 bytes. One excess byte is sufficient to
   reject an oversized stream without unbounded materialization.
4. Input is decoded as strict UTF-8. Invalid or unencodable input fails with a
   fixed package-owned `ConfigError` that does not reproduce the rejected bytes
   or text.
5. The accepted decoded text is preserved exactly, including trailing newline
   characters. Transport framing is not stripped or normalized because a
   newline can change the authoritative tokenizer result.
6. Input validation completes before `PostgresConfigStore` construction and
   before PostgreSQL token-counting work. Invalid local input therefore cannot
   cause database acquisition merely because the CLI was invoked.
7. Successful input still goes only to `TokenCounter`, preserving PostgreSQL
   `pg_tiktoken` as the tokenization authority; no Python tokenizer fallback is
   introduced.
8. Existing one-shot ownership rules remain in force: the token counter closes
   before its owned configuration store on both success and failure.

The byte ceiling is a resource/privacy boundary for this CLI path, not a claim
that 1 MiB is a universal model context limit. Model/provider token limits remain
separate authorities.

## Failure and recovery semantics

Oversized or malformed UTF-8 input is a local validation failure. The operator
must correct the input source or deliberately split content before retrying; the
CLI does not truncate, normalize, mask, or partially tokenize the rejected
content.

Because stdin content is intentionally not replayed from package persistence,
callers that require retry after a local process failure must retain their own
authorized source. Shell pipelines should avoid commands such as `echo` when a
trailing newline is not intended; `printf '%s'` is the deterministic no-newline
example.

This boundary does not claim that stdin is a universal secrets manager or that
operating-system administrators cannot inspect process memory or inherited file
descriptors. It removes the specific avoidable argv exposure while keeping the
content usable for its intended computation.

## Verification

The candidate regression suite proves:

- parser acceptance of explicit `--stdin` and absence of a parsed `text` field;
- rejection of legacy `--text` content without sentinel reflection;
- exact UTF-8 and trailing-newline preservation into `TokenCounter`;
- rejection above the 1 MiB byte ceiling before configuration/database work;
- fixed content-free diagnostics for invalid UTF-8 and text adapters that cannot
  be encoded as UTF-8; and
- deterministic token-counter/configuration cleanup after success and failure.

Final acceptance additionally requires the repository's Python 3.10/3.12/3.14,
exact owned production statement/branch coverage, public-docstring, package,
security/SAST, exact-source, required central review, and release-acceptance
gates on one unchanged source head.

## References

MITRE. (2026, April 30). *CWE-214: Invocation of process using visible sensitive
information* (CWE Version 4.20). Common Weakness Enumeration.
https://cwe.mitre.org/data/definitions/214.html

Python Software Foundation. (2026). *Command line and environment — Python
3.14.6 documentation*. https://docs.python.org/3.14/using/cmdline.html

Python Software Foundation. (2026). *sys — System-specific parameters and
functions — Python 3.14.6 documentation*.
https://docs.python.org/3.14/library/sys.html#sys.argv
