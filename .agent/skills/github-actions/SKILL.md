---
name: github-actions
description: 'Create, review, and troubleshoot GitHub Actions workflows for the Cordyceps Lab repository. Use for CI, scheduled checks, Python tests, Docker builds, permissions, or workflow failures.'
---

# GitHub Actions

## Workflow
1. Inspect existing workflows under `.github/workflows/` and repository commands in `README.md` before editing.
2. Keep jobs narrow and reproducible: install declared dependencies, run focused tests, then run repository validators such as `tools/check_base_image.py`.
3. Pin action major versions and use least-privilege permissions; keep secrets in GitHub Actions secrets and never echo them.
4. Make architecture, Python, Docker, and path assumptions explicit in the matrix or job setup.
5. Validate YAML syntax and run equivalent commands locally where practical.
6. Review changed-file scope, cache keys, failure output, artifact retention, and scheduled workflow behavior.

## Completion Checks
- A workflow fails on real validation errors rather than masking them with `continue-on-error`.
- CI checks match the supported `amd64` and `aarch64` add-on targets.
- Workflow documentation and badges, if present, remain accurate.
