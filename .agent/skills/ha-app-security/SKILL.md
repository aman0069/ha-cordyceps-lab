---
name: ha-app-security
description: 'Review and harden the Cordyceps Lab Home Assistant add-on for authentication, QR tokens, redirects, input validation, data exposure, secrets, and container security.'
---

# Home Assistant App Security

## Workflow
1. Read `docs/CONTRACT.md`, the route in `cordyceps_lds/app/main.py`, and the relevant data access code before proposing a fix.
2. Trace untrusted inputs from QR path, query string, request body, headers, configuration, and export table names to their sink.
3. Verify token entropy and lookup behavior, constant-time comparisons where applicable, authorization on mutating routes, and the intentionally unauthenticated `/health` endpoint.
4. Constrain redirects to the configured `ha_base_url`; reject unsafe schemes or attacker-controlled destinations.
5. Confirm exports expose only contract-approved tables and that logs/errors do not disclose tokens, configuration secrets, or sensitive lab data.
6. Add a regression test for each fixed boundary, then run the focused pytest suite and inspect container configuration.

## Guardrails
- Never put strain, dates, recipes, weights, or operator data in QR payloads.
- Never commit real tokens or secrets.
- Do not turn analysis or scanning into a control path that changes Home Assistant setpoints.
