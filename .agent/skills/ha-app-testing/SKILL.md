---
name: ha-app-testing
description: 'Test the Cordyceps Lab Home Assistant add-on, FastAPI endpoints, SQLite behavior, YAML integration, QR labels, and exports. Use when adding tests, reproducing failures, or validating changes.'
---

# Home Assistant App Testing

## Workflow
1. Identify the smallest behavior under test and read its contract and nearby test fixture.
2. Reproduce the failure with a focused test or command before broadening scope.
3. Cover the happy path plus the boundary that could regress: duplicate tokens, illegal transitions, incomplete transfers, missing sensors, null weights, or malformed input.
4. Run `cd cordyceps_lds; python -m pytest tests -q` for service changes.
5. For label changes, run the documented `tools/make_labels.py` flow and verify the generated QR decodes to only the expected redirect URL.
6. Report unrelated failures separately; do not weaken assertions to accommodate them.

## Completion Checks
- Tests assert observable API/database behavior, not private implementation details.
- Missing data remains distinguishable from zero.
- Test databases and generated artifacts do not modify production samples or tracked fixtures.
- A passing focused check is followed by the broadest inexpensive relevant check.
