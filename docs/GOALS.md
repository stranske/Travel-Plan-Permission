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

## Current Blocker: startup_failure (Under Investigation)

**Issue discovered 2025-12-22:**

### Original Problem (Fixed)
The `reusable-10-ci-python.yml` workflow used composite actions with relative paths:
```yaml
uses: ./.github/actions/python-ci-setup
```
This was fixed in Workflows repo PR #49 by inlining the composite action logic.

### Current Problem (Unresolved)
Despite the fix, CI still fails with `startup_failure`:
- **SHA updated:** `dc46ca4` → `07c3a6ce10ff00953624e9f0705c44190ec7b33c` (PR #49 merge)
- **Failure type:** `startup_failure` with 0 jobs created
- **No error message:** GitHub API provides no details for startup failures

### Investigation Findings (2025-12-22)

**Verified working:**
- ✅ SHA `07c3a6c` exists and contains the inlined composite action fix
- ✅ Reusable workflow YAML is valid (2050 lines, parses correctly)
- ✅ No relative action paths (`uses: ./`) remain in the workflow
- ✅ Workflows repo is public and accessible
- ✅ "Allow all actions and reusable workflows" is enabled in repo settings
- ✅ Fork pull request settings are not restrictive

**Verified NOT the cause:**
- ❌ Composite action paths (fixed in PR #49)
- ❌ Repository access settings (all actions allowed)
- ❌ YAML syntax errors (validated locally)
- ❌ Missing required inputs (all have defaults)

**Key observations:**
1. The Workflows repo's own "Selftest CI" passes (runs locally)
2. The Workflows repo's "Maint 62 Integration Consumer" ran at `05:12:21Z` on SHA `dc46ca4`
3. PR #49 merged at `05:12:43Z` creating SHA `07c3a6c` - **22 seconds after** the test
4. No integration test has run yet with the fixed SHA
5. Other workflows in this repo (agents-70-orchestrator) start successfully

**Possible remaining causes:**
1. **GitHub caching issue** - GitHub may cache workflow resolution
2. **Expression evaluation failure** - Complex matrix expression in reusable workflow
3. **Unknown GitHub Actions limitation** - Something specific to external reusable workflow calls
4. **Timing/propagation delay** - New SHA may not have fully propagated

### Next Steps

1. **Wait and retry** - GitHub may need time to propagate the new SHA
2. **Trigger new integration consumer run** in Workflows repo to validate fix
3. **Try branch reference** as diagnostic: `@main` instead of SHA
4. **Check GitHub status** for any Actions-related incidents
5. **Open GitHub support ticket** if issue persists (no actionable error message)

## What Works Now

| Feature | Status | Notes |
|---------|--------|-------|
| `agents-63-issue-intake.yml` | ✅ Works | Thin caller to reusable-agents-issue-bridge.yml |
| `agents-70-orchestrator.yml` | ✅ Works | Thin caller to reusable-16-agents.yml (runs, has own failures) |
| Labels | ✅ Synced | All required labels created |
| Secrets | ✅ Configured | SERVICE_BOT_PAT, OWNER_PR_PAT, ACTIONS_BOT_PAT |
| Reusable Python CI | ❌ Blocked | startup_failure - cause under investigation |

## Immediate Next Steps

1. **Trigger Workflows integration test** to validate PR #49 fix works externally
2. **Retry CI in this repo** after integration test passes
3. **Continue testing agent workflows** which do work
4. **Convert existing Issues** to Issues.txt format

## Tasks Pending

- [ ] Trigger Maint 62 Integration Consumer in Workflows repo with current main
- [ ] Re-run CI after integration test validates the fix
- [ ] Evaluate labeler.yml and archive if not useful
- [ ] Rewrite GitHub Issues #3-19 into Issues.txt format
- [ ] If startup_failure persists after integration test passes, open GitHub support ticket

## References

- [belt-automation-plan.md](./belt-automation-plan.md) - Thin caller pattern
- [ci-system-guide.md](./ci-system-guide.md) - CI integration docs
- [agent-integration-status.md](./agent-integration-status.md) - Agent setup status
