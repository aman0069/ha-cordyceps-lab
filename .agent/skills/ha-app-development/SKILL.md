---
name: ha-app-development
description: 'Develop the Cordyceps Lab Home Assistant add-on and FastAPI service. Use for API, SQLite, IDs, stages, transfers, scans, exports, or app behavior changes.'
---

# Home Assistant App Development

## Workflow
1. Read `docs/CONTRACT.md` and the closest implementation in `cordyceps_lds/app/` before editing.
2. Trace the request from route or caller to the owning domain module (`ids.py`, `stages.py`, `db.py`, or `main.py`).
3. Preserve opaque QR tokens, stable entity and ID formats, append-only event history, and explicit `NULL`/`missing` sensor semantics.
4. Implement the smallest change at the owning abstraction. Do not make scanning write data or silently infer biological values.
5. Add or update a focused test under `cordyceps_lds/tests/` for success, invalid input, and the relevant boundary case.
6. Run `cd cordyceps_lds; python -m pytest tests -q` and inspect the diff for contract or schema drift.

## Completion Checks
- API errors identify the missing or invalid field and use the established status code.
- Stage transitions remain legal, auditable, and timezone-aware.
- Exports and learning inputs retain empty values as empty values, never zero-fill them.
- No setpoint or Home Assistant control changes as a side effect of analysis.
