# Bounded control-plane JSON implementation plan

> **Required workflow:** Use test-driven development and verification before completion.

**Goal:** Prevent provider control-plane responses from allocating unbounded
worker memory while preserving all successful public endpoint contracts.

**Architecture:** Add a dedicated positive byte budget, make the existing bounded
UTF-8 reader accept an explicit limit, route every control-plane JSON object
through that reader, and retain the independent provider-file budget.

## Global constraints

- The default is exactly 1 MiB per control-plane response.
- Booleans, non-integers, zero, and negative values are invalid.
- Actual decoded bytes are authoritative.
- `Content-Length` is only an early rejection signal.
- `response.json()` and `response.text()` are forbidden for control-plane JSON.
- A callable `content.iter_chunked` stream is required.
- Provider output/error files retain `max_download_bytes` independently.
- Oversize and decode errors never contain provider content.
- Successful upload/create/status/cancel dictionaries are unchanged.
- Production statement, branch, and docstring coverage remain 100%.
- Python 3.10, 3.12, and 3.14 remain supported.

## Task 1: Define the failing contract

**Files:**
- Create: `tests/test_bounded_control_plane_json.py`

- [x] Validate constructor values and the one-MiB default.
- [x] Reject declared oversize before reading.
- [x] Reject actual decoded-byte overflow with an understated header.
- [x] Accept an exact-limit JSON object.
- [x] Reject invalid UTF-8 without content leakage.
- [x] Preserve malformed and non-object JSON errors.
- [x] Prove whole-body JSON/text helpers are never called.
- [x] Exercise upload, creation, status, and cancellation.
- [x] Prove provider-file downloads retain their independent limit.
- [x] Record exact pre-implementation red evidence.

## Task 2: Implement the explicit response budget

**Files:**
- Modify: `pg_llm_batch/batch_api_client.py`

- [x] Add `DEFAULT_MAX_CONTROL_RESPONSE_BYTES`.
- [x] Add and validate `max_control_response_bytes`.
- [x] Store the active limit.
- [x] Require `max_bytes` in `_download_limit_error`.
- [x] Require `max_bytes` in `_read_bounded_utf8`.
- [x] Decode control-plane JSON through bounded bytes and `json.loads()`.
- [x] Route provider files through `self.max_download_bytes`.
- [x] Preserve endpoint status and result contracts.

## Task 3: Document the operator boundary

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Maintain: `docs/doctoring/bounded-control-plane-json.md`

- [x] Document default, override, and independent budgets.
- [x] Document fail-closed response-adapter requirements.
- [x] Add the feature under `Unreleased`.

## Task 4: Verify, review, and merge

- [x] Run focused bounded-response tests.
- [x] Run the complete non-integration suite.
- [x] Run Ruff and compileall.
- [x] Require 100% production docstrings.
- [x] Require 100% production statement and branch coverage.
- [x] Require lockfile freshness.
- [x] Build wheel and source distribution.
- [x] Validate Compose and both runtime images.
- [ ] Inspect every current-head human, CodeRabbit, OpenCode, and security finding.
- [ ] Require exact-head CI, SAST Semgrep, and Security Scan success.
- [ ] Merge only the reviewed exact head.
- [ ] Re-query the PR queue and continue with the next bounded product gap.
