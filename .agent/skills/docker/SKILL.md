---
name: docker
description: 'Build, run, inspect, and troubleshoot Docker images and Compose services for the Cordyceps Lab Home Assistant add-on. Use for Dockerfile, docker-compose, ports, volumes, health, or image issues.'
---

# Docker

## Workflow
1. Read `cordyceps_lds/Dockerfile`, `docker-compose.yml`, `config.yaml`, and the relevant README section together.
2. Confirm the container listens on `8099`, the compose host mapping is intentional, persistent data is mounted at the documented path, and health/watchdog behavior remains valid.
3. Keep the image minimal: pin compatible base/dependency ranges, avoid copying secrets, and run as the expected Home Assistant service user.
4. Build the image and start the narrowest Compose service needed to reproduce the issue; inspect logs and health status.
5. Validate startup, `/health`, persistence across restart, and published host-port behavior.
6. Clean up only resources created for the check and document any host prerequisites.

## Guardrails
- Do not confuse the internal container port with the QR-encoded host port.
- Do not claim architecture support unless the base image publishes it; run `python tools/check_base_image.py` after changing the base tag or `arch` list.
