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

## Current Blocker: Composite Actions

**Issue discovered 2024-12-22:**

The `reusable-10-ci-python.yml` workflow uses composite actions with relative paths:

```yaml
uses: ./.github/actions/python-ci-setup
```

When called from Travel-Plan-Permission, this resolves to the CALLER repo's
`.github/actions/` directory, not the Workflows repo. This causes `startup_failure`
because the action doesn't exist in the caller repo.

**Required fix (in Workflows repo):**

The reusable workflows need to be refactored so they work when called externally.
Options:

1. Publish composite actions to a separate action repo
2. Inline the composite action logic into the reusable workflow
3. Use a different pattern that works cross-repo

## What Works Now

| Feature | Status | Notes |
|---------|--------|-------|
| `agents-63-issue-intake.yml` | ✅ Works | Thin caller to reusable-agents-issue-bridge.yml |
| `agents-70-orchestrator.yml` | ✅ Created | Thin caller to reusable-16-agents.yml |
| Labels | ✅ Synced | All required labels created |
| Secrets | ✅ Configured | SERVICE_BOT_PAT, OWNER_PR_PAT, ACTIONS_BOT_PAT |
| Reusable Python CI | ❌ Blocked | Composite action path issue |

## Immediate Next Steps

1. **Document the composite action issue** as a problem to fix in Workflows repo
2. **Do NOT create standalone CI** - wait for Workflows fix
3. **Continue testing agent workflows** which do work
4. **Convert existing Issues** to Issues.txt format

## Tasks Pending

- [ ] Evaluate labeler.yml and archive if not useful
- [ ] Rewrite GitHub Issues #3-19 into Issues.txt format
- [ ] Coordinate with Workflows repo to fix reusable CI for external callers

## References

- [belt-automation-plan.md](./belt-automation-plan.md) - Thin caller pattern
- [ci-system-guide.md](./ci-system-guide.md) - CI integration docs
- [agent-integration-status.md](./agent-integration-status.md) - Agent setup status
