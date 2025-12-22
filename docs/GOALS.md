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

## Current Blocker: RESOLVED - Mixing Job Types Causes startup_failure

**Issue discovered 2025-12-22, RESOLVED 2025-12-22**

### Root Cause Identified

**GitHub Actions fails with `startup_failure` when a workflow contains BOTH:**
1. A job that calls a reusable workflow (`uses:`)  
2. Regular jobs (`runs-on:`)

This is likely a GitHub Actions bug or undocumented limitation.

### Proof

```yaml
# ❌ FAILS with startup_failure - mixed job types
jobs:
  local-job:
    runs-on: ubuntu-latest
    steps: [...]
  
  python-ci:
    uses: stranske/Workflows/.github/workflows/reusable-10-ci-python.yml@SHA

# ✅ WORKS - only reusable workflow job
jobs:
  python-ci:
    uses: stranske/Workflows/.github/workflows/reusable-10-ci-python.yml@SHA
```

### Workarounds

1. **Separate workflows** - Put reusable workflow call in its own file, local jobs in another
2. **Use only reusable workflows** - Move all logic to Workflows repo
3. **Wait for GitHub fix** - This may be a bug that gets resolved

### Additional Bug Found - FIXED

The reusable workflow had a bug: `BLACK_VERSION: unbound variable` in the
"Prepare Python environment" step. The script used `set -u` (fail on undefined
variables) but referenced `BLACK_VERSION` before it was defined.

**Status**: ✅ FIXED in Workflows repo (2025-12-22)  
**Fix**: Changed `$BLACK_VERSION` to `${BLACK_VERSION:-}` (default empty string)

### Bug: Incompatible Default Version Pins

The reusable workflow defaults to incompatible versions:
- `pydantic==2.10.3` (default)
- `pydantic-core==2.23.4` (default)

But pydantic 2.10.x requires pydantic-core 2.27.x. This causes dependency
resolution failures when consumers don't override these values.

**Workaround**: Add to consumer's `autofix-versions.env`:
```bash
PYDANTIC_VERSION=2.10.4
PYDANTIC_CORE_VERSION=2.27.2
```

**Fix needed in Workflows repo**: Update default PYDANTIC_CORE_VERSION to match
pydantic's requirements, or don't install pydantic-core separately (let pip
resolve it as a transitive dependency).

## What Works Now

| Feature | Status | Notes |
|---------|--------|-------|
| `agents-63-issue-intake.yml` | ✅ Works | Thin caller to reusable-agents-issue-bridge.yml |
| `agents-70-orchestrator.yml` | ✅ Works | Thin caller to reusable-16-agents.yml |
| Labels | ✅ Synced | All required labels created |
| Secrets | ✅ Configured | SERVICE_BOT_PAT, OWNER_PR_PAT, ACTIONS_BOT_PAT |
| `ci.yml` | ✅ Works | Thin caller to reusable-10-ci-python.yml |
| `lint.yml` | ✅ Works | Local linting jobs (separate file for mixed job workaround) |
| Reusable Python CI | ✅ Fixed | BLACK_VERSION bug resolved |
| Gate job pattern | ❌ Blocked | Mixing job types causes startup_failure |

## Immediate Next Steps

1. ~~**Fix BLACK_VERSION bug** in Workflows repo~~ ✅ DONE
2. **Decide on gate pattern** - use workflow_run trigger or remove gate entirely
3. **Re-enable full CI** once gate pattern is resolved
4. **Continue testing agent workflows** which do work

## Tasks Pending

- [ ] Report `needs` + reusable workflow bug to GitHub or find documentation
- [x] Fix BLACK_VERSION unbound variable in Workflows repo
- [ ] Implement alternative gate pattern (workflow_run or required checks)
- [ ] Re-enable actionlint, docs-lint, schema-validate jobs
- [x] Evaluate labeler.yml and archive if not useful (archived 2025-12-22)
- [ ] Rewrite GitHub Issues #3-19 into Issues.txt format

## References

- [belt-automation-plan.md](./belt-automation-plan.md) - Thin caller pattern
- [ci-system-guide.md](./ci-system-guide.md) - CI integration docs
- [agent-integration-status.md](./agent-integration-status.md) - Agent setup status
