# Bounded control-stream chunk RED/GREEN evidence

## Risk captured

The bounded control-plane reader initially accepted only ordinary byte streams.
Two adapter boundaries remained commercially material:

1. a custom adapter could yield a non-byte value and trigger an incidental
   Python `TypeError` whose message included provider-controlled content rather
   than the package's bounded, body-free gateway error contract; and
2. a multi-byte-formatted `memoryview` could have an element count smaller than
   its underlying byte count, so measuring it with `len(view)` could admit more
   decoded bytes than the configured resource limit.

The permanent regressions are
`test_non_byte_stream_chunk_fails_closed_without_content_leakage` and the two
`tests/test_bounded_memoryview_contract.py` cases.

## RED evidence

The malformed-adapter regression failed in hosted CI run `30980533617` before
its implementation because the production reader reached `len(chunk)` on a
provider-controlled string. The observed exception was an incidental type
failure rather than the required `GatewayError` with
`{"error_type": "InvalidByteChunk"}`.

The byte-accounting regression was committed at exact head
`a97cc3d9c348100a7619aaa51774b7676892c46d`. Hosted CI run `30981583910` failed
on Python 3.10, 3.12, and 3.14 for the intended reason: a four-byte
`memoryview(array("I", [0x41414141]))` was treated as one element, so a
three-byte limit did not raise `GatewayError`. The corresponding container jobs
succeeded, isolating the failure to the new behavioral contract.

## GREEN evidence

At exact implementation head
`44297d2b021189861c8e3dfa3380f36887fd5af2`, the reader:

- accepts only `bytes`, `bytearray`, and `memoryview` chunks;
- reports malformed chunks through the bounded `InvalidByteChunk` category
  without copying provider content;
- measures memory views with `memoryview.nbytes` rather than element count; and
- admits the complete underlying bytes only when they fit the remaining budget.

Exact-head CI run `30982185022`, SAST Semgrep run `30982185101`, and Security
Scan run `30982184959` succeeded. The CI gate included the complete
non-integration suite on Python 3.10, 3.12, and 3.14, compilation, Ruff, 100%
production public-docstring coverage, 100% production statement and branch
coverage, lock freshness, package builds, Compose validation, and both container
builds.

A temporary one-shot run on the same implementation head failed only because
its branch-history parent assertion had become stale after concurrent commits;
it did not execute the implementation step. The standard exact-head product,
coverage, packaging, container, SAST, and security gates all succeeded. The
stale helper workflow was removed from the final diff rather than weakening its
guard.

## Maintained contract

Permanent tests prove both the rejection path and exact-limit success. A
four-byte memory view is rejected under a three-byte budget and decodes to
`AAAA` under a four-byte budget. A malformed adapter value is never echoed in
exception text or structured response data.
