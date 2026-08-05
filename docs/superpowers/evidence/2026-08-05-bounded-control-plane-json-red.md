# Bounded control-plane JSON red evidence

- Pre-implementation head: `c98231b16703a927de49e9fb09a1f505e6950089`
- Command: `uv run pytest -q tests/test_bounded_control_plane_json.py`
- Exit status: nonzero, required by the one-shot workflow
- Observed contract failure: `BatchAPIClient` did not accept
  `max_control_response_bytes`, and control-plane JSON still used
  whole-body response decoding.

The workflow required both the new field name and pytest failure markers;
unrelated setup failures could not satisfy the RED gate.
