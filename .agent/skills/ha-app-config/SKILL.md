---
name: ha-app-config
description: 'Configure Home Assistant add-on options, entity mappings, secrets, ports, packages, and dashboards for the Cordyceps Lab. Use for config.yaml, sensor maps, install instructions, or HA integration changes.'
---

# Home Assistant App Configuration

## Workflow
1. Read `docs/CONTRACT.md` and `README.md`; inspect `cordyceps_lds/config.yaml` before changing configuration.
2. Keep add-on metadata, `arch`, ports, watchdog, options, and schema internally consistent. There must be only one repository `config.yaml`, at `cordyceps_lds/config.yaml`.
3. Treat empty entity options as intentionally unavailable. Map them to `none`/missing and preserve null payloads rather than guessing an entity or value.
4. Update `homeassistant/packages/` and dashboards only when the integration contract requires it; entity IDs are configured through the add-on options, not hard-coded in the generated map.
5. Update README or `cordyceps_lds/DOCS.md` when an operator-visible setting, port, or installation step changes.
6. Validate YAML syntax and run the focused app tests after configuration changes.

## Guardrails
- Keep the container port at `8099` unless the contract explicitly changes it; the published host port is separate.
- Treat the QR host port as permanent after labels are printed; changing `ha_base_url` is the preferred later adjustment.
- Do not expand architectures beyond images actually published by the Home Assistant base image.
