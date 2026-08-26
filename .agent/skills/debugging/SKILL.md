---
name: debugging
description: 'Debug failures in the Cordyceps Lab Home Assistant add-on, Python service, YAML integration, Docker runtime, or CI. Use for errors, regressions, flaky tests, startup failures, or unexpected data.'
---

# Debugging

## Workflow
1. Capture the exact failing command, error, environment, and smallest reproducible input.
2. Start at the concrete anchor: failing test, route, log line, YAML key, Docker health result, or CI step.
3. Read only the nearest owning implementation and a neighboring test or call site; state one falsifiable hypothesis.
4. Run the cheapest discriminating check before broad exploration.
5. Fix the root cause at the controlling abstraction, preserving contract semantics such as missing versus zero and scan versus confirm.
6. Rerun the same focused check, then `cd cordyceps_lds; python -m pytest tests -q` when relevant.
7. Report what was proven, what remains uncertain, and any unrelated failure separately.

## Guardrails
- Do not hide errors with broad exception handling, retries, or default values without evidence.
- Do not delete user changes or generated evidence while reproducing a problem.
- Prefer a minimal regression test over a speculative refactor.
