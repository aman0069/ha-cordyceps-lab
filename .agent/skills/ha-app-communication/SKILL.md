---
name: ha-app-communication
description: 'Document, explain, and communicate changes to the Cordyceps Lab Home Assistant add-on. Use for README, DOCS, CHANGELOG, contract notes, operator guidance, or release summaries.'
---

# Home Assistant App Communication

## Workflow
1. Identify the audience: lab operator, Home Assistant administrator, developer, or release reviewer.
2. Check `docs/CONTRACT.md` and the current README/DOCS wording before writing; preserve established names such as batch, jar, stage, transfer, and source flag.
3. State the user-visible behavior, required configuration, migration impact, and validation command in concrete language.
4. Call out irreversible operations and operational hazards, especially QR host-port changes, printed labels, backups, and missing sensors.
5. Update the narrowest relevant document and changelog entry without duplicating contradictory instructions.
6. Verify commands, paths, ports, architecture claims, and examples against the current files.

## Quality Bar
- Operators can follow the steps without inferring hidden defaults.
- Unknown values are described as unknown, not estimated.
- Security-sensitive values are represented as placeholders.
- Documentation matches the actual API, entity names, supported architectures, and test command.
