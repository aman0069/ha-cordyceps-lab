---
name: yaml
description: 'Edit and validate Home Assistant YAML packages, dashboards, add-on metadata, and repository configuration. Use for Lovelace views, templates, automations, schemas, or YAML diagnostics.'
---

# YAML

## Workflow
1. Identify the owning YAML consumer: Home Assistant packages/dashboards, Supervisor add-on metadata, Docker Compose, or CI.
2. Read the complete nearby mapping and preserve its existing schema, anchors, quoting, and entity naming conventions.
3. Make the smallest structural change; avoid duplicate keys, implicit type changes, guessed defaults, and legacy Home Assistant template syntax.
4. Validate parsing with a YAML-aware tool when available and inspect the rendered structure for the target consumer.
5. For Home Assistant changes, verify null/missing behavior, entity IDs, service targets, and dashboard card references.
6. Run the relevant app tests and document any validation that requires a live Home Assistant instance.

## Guardrails
- Keep secrets out of tracked YAML; use `secrets.yaml` references or placeholders.
- Do not hard-code configured sensor entity IDs into `cm2_sensor_map.yaml` when the add-on configuration owns them.
