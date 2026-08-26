---
name: multi-arch-build
description: 'Build and validate Home Assistant add-on images across amd64 and aarch64. Use for base image tags, architecture metadata, Buildx, registry manifests, or Raspberry Pi compatibility.'
---

# Multi-Architecture Build

## Workflow
1. Read `cordyceps_lds/config.yaml`, `Dockerfile`, repository CI, and the base-image comments in `README.md`.
2. Treat `arch` metadata and the base image manifest as one contract. Confirm every declared architecture is actually published.
3. Run `python tools/check_base_image.py` before spending time on a full build when the base tag or architecture list changes.
4. Build with Buildx for `linux/amd64,linux/arm64` or the exact supported targets, using separate cache keys and no secret leakage.
5. Inspect the resulting manifest, labels, startup command, `/health`, and architecture-specific native dependencies.
6. Record unsupported targets explicitly; do not add `armv7`, `armhf`, or `i386` based on assumption.

## Completion Checks
- Both supported targets resolve the same application contract.
- The image labels and add-on metadata remain consistent.
- The base tag uses the documented `<alpine-version>-<build-version>` format rather than a guessed HA Core version.
