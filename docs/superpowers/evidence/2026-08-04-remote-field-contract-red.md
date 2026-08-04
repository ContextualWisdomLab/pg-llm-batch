# Durable Remote Field Contract Red Evidence

- Pre-fix head: `3a66ba92951ed0a48be069fd7952e7e393027cc6`
- Command: `uv run pytest -q tests/test_remote_batch_state_contracts.py -k remote_field_contract`
- Expected result: failure before implementation
- Actual pytest exit code: `1`
- Actual result: `7 failed, 9 deselected`
- Failed contracts:
  - `test_remote_field_contract_rejects_invalid_optional_ids_before_database_access`
    failed in all three `input_file_id`, `output_file_id`, and `error_file_id`
    parameter cases because persistence did not raise `ValueError` before database
    access.
  - `test_remote_field_contract_blocks_invalid_optional_id_before_custom_recorder`
    failed because the durable client did not raise `GatewayError` before invoking
    the recorder.
  - `test_remote_field_contract_sanitizes_nul_text_before_custom_recorder` failed
    because NUL-bearing endpoint and status text reached the recorder unchanged.
  - `test_remote_field_contract_normalizes_nul_optional_text` failed because the
    persisted snapshot retained NUL-bearing endpoint and status text.
  - `test_remote_field_contract_adds_database_checks` failed with the identifier
    constraint count at `0` instead of `4`.
- Observed boundary: optional provider file identifiers and NUL-bearing
  descriptive text could reach custom recorders or PostgreSQL without
  the documented durable gateway validation contract.
