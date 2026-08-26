---
name: git
description: 'Work safely with Git in the Cordyceps Lab repository. Use for status, diff, history, blame, branch-aware changes, release notes, or preparing a review.'
---

# Git

## Workflow
1. Start with `git status --short` and inspect the relevant diff before changing files.
2. Read local history with `git log` or `git blame` only when it clarifies an ownership or compatibility decision.
3. Keep edits focused and preserve unrelated user changes; never reset, checkout, or clean destructively without explicit approval.
4. Review the final diff for accidental generated files, secrets, broad formatting churn, and contract changes.
5. Run the narrowest relevant validation, then the repository smoke suite when the change crosses module boundaries.
6. Summarize changed files, validation, and any residual risk. Do not commit unless explicitly requested.

## Review Checklist
- API, schema, IDs, YAML, docs, and CI changes agree.
- New behavior has a focused regression test.
- No credentials, local paths, build output, or production data were added.
- Reversible and irreversible operator impacts are called out.
