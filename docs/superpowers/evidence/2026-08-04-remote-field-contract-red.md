# Durable Remote Field Contract Red Evidence

- Pre-fix head: `3a66ba92951ed0a48be069fd7952e7e393027cc6`
- Command: `uv run pytest -q tests/test_remote_batch_state_contracts.py -k remote_field_contract`
- Expected result: failure before implementation
- Observed boundary: optional provider file identifiers and NUL-bearing
  descriptive text could reach custom recorders or PostgreSQL without
  the documented durable gateway validation contract.
