---
name: bashio
description: 'Work with Home Assistant add-on shell conventions and Bashio-style lifecycle, options, logging, and service integration. Use when editing run scripts, service startup, or add-on environment handling.'
---

# Bashio

## Workflow
1. Inspect `cordyceps_lds/run.sh`, the Dockerfile, and add-on `config.yaml` to understand startup ownership and environment inputs.
2. Treat Supervisor-provided options as untrusted configuration: validate required values, normalize paths, and preserve empty values as missing.
3. Use strict, portable shell practices and clear logs; never print tokens or secret values.
4. Keep startup idempotent and fail early when required configuration is invalid, while allowing optional sensors to remain absent.
5. Check signal handling, exit codes, permissions, and the watchdog health endpoint.
6. Run shell syntax checks and the app smoke suite; test both valid configuration and a missing-required-value path.

## Guardrails
- Do not add a second `config.yaml`.
- Do not make shell startup mutate Home Assistant setpoints or silently invent entity IDs.
