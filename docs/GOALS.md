# Integration Goals

This document captures the primary objectives for this repository to prevent
losing focus during implementation.

## Phase Goal: External Workflow Consumer Pattern

**This repository is the FIRST external consumer of stranske/Workflows.**

The purpose is to:

1. **Test the pattern** of using a centralized Workflows repo from satellite repos
2. **Identify coordination issues** that need to be resolved in the Workflows repo
3. **Establish a reusable template** that other repos can follow
4. **Minimize duplication** - satellite repos should contain thin callers only

## Design Principles

1. **Workflows repo is the single source of truth** for automation logic
2. **Satellite repos use thin callers** that reference reusable workflows
3. **No standalone workflow duplication** in satellite repos
4. **Fix issues at the source** - if something doesn't work cross-repo, fix it in
   Workflows, don't work around it locally

## Current Blocker: RESOLVED - `needs` on Reusable Workflow Jobs

**Issue discovered 2025-12-22, RESOLVED 2025-12-22**

### Root Cause Identified

**The `startup_failure` was caused by having a regular job with `needs: [reusable-workflow-job]`.**

When a workflow has:
1. A job that calls a reusable workflow (`uses:`)
2. Another job with `needs:` referencing that reusable workflow job

GitHub Actions fails at startup with no error message. This appears to be a GitHub Actions bug or undocumented limitation.

### Proof

```yaml
# ❌ FAILS with startup_failure
jobs:
  python-ci:
    uses: stranske/Workflows/.github/workflows/reusable-10-ci-python.yml@SHA
    ...
  gate:
    needs: [python-ci]  # THIS CAUSES startup_failure
    runs-on: ubuntu-latest
    ...

# ✅ WORKS - no needs referencing reusable workflow
jobs:
  python-ci:
    uses: stranske/Workflows/.github/workflows/reusable-10-ci-python.yml@SHA
    ...
  gate:
    runs-on: ubuntu-latest  # No needs clause
    ...
```

### Workarounds

1. **Remove gate job entirely** - Let GitHub's required checks handle gating
2. **Use workflow_run trigger** - Separate workflow that runs after CI completes
3. **Wait for GitHub fix** - This may be a bug that gets resolved

### Previous Investigation (for reference)

The original composite action path issue was fixed in PR #49 (SHA `07c3a6c`).
That fix was valid - the reusable workflow works when called directly.
The `startup_failure` was caused by the `needs` clause, not the workflow itself.

## What Works Now

| Feature | Status | Notes |
|---------|--------|-------|
| `agents-63-issue-intake.yml` | ✅ Works | Thin caller to reusable-agents-issue-bridge.yml |
| `agents-70-orchestrator.yml` | ✅ Works | Thin caller to reusable-16-agents.yml (runs, has own failures) |
| Labels | ✅ Synced | All required labels created |
| Secrets | ✅ Configured | SERVICE_BOT_PAT, OWNER_PR_PAT, ACTIONS_BOT_PAT |
| Reusable Python CI | ✅ Works | Works without gate job using `needs` |
| Gate job pattern | ❌ Blocked | `needs` on reusable workflow jobs causes startup_failure |

## Immediate Next Steps

1. **Fix BLACK_VERSION bug** in Workflows repo - unbound variable when format_check=false
2. **Decide on gate pattern** - use workflow_run trigger or remove gate entirely
3. **Re-enable full CI** once gate pattern is resolved
4. **Continue testing agent workflows** which do work

## Tasks Pending

- [ ] Report `needs` + reusable workflow bug to GitHub or find documentation
- [ ] Fix BLACK_VERSION unbound variable in Workflows repo
- [ ] Implement alternative gate pattern (workflow_run or required checks)
- [ ] Re-enable actionlint, docs-lint, schema-validate jobs
- [ ] Evaluate labeler.yml and archive if not useful
- [ ] Rewrite GitHub Issues #3-19 into Issues.txt format

## References

- [belt-automation-plan.md](./belt-automation-plan.md) - Thin caller pattern
- [ci-system-guide.md](./ci-system-guide.md) - CI integration docs
- [agent-integration-status.md](./agent-integration-status.md) - Agent setup status
