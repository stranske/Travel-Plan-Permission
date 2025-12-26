# Belt Automation Integration Plan

This document outlines the plan for integrating the Codex belt automation system from stranske/Workflows into Travel-Plan-Permission **using the reusable workflow pattern** (not duplication).

## ⚠️ Key Principle: Don't Duplicate, Reference

The Workflows repo is the **centralized source of truth**. Satellite repos should use **thin caller workflows** that reference the Workflows repo's reusable workflows:

```yaml
# Correct: Reference the centralized workflow
uses: stranske/Workflows/.github/workflows/reusable-16-agents.yml@main

# Wrong: Copy the entire workflow locally
# (creates maintenance burden and alignment drift)
```

### Benefits of This Pattern
- **Automatic updates**: When Workflows repo improves, all consumers benefit
- **No drift**: Single source of truth for automation logic
- **Reduced maintenance**: Satellite repos only maintain thin callers
- **Version pinning**: Can pin to `@main`, `@v1`, or specific SHA for stability

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    stranske/Workflows (Hub)                      │
├─────────────────────────────────────────────────────────────────┤
│  reusable-16-agents.yml        (orchestration, keepalive)       │
│  reusable-agents-issue-bridge.yml  (issue→PR conversion)        │
│  reusable-70-orchestrator-init.yml (init phase)                 │
│  reusable-70-orchestrator-main.yml (main phase)                 │
│  agents-71/72/73-*.yml         (belt dispatcher/worker/conveyor)│
└───────────────────────┬─────────────────────────────────────────┘
                        │ workflow_call
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│              Travel-Plan-Permission (Satellite)                  │
├─────────────────────────────────────────────────────────────────┤
│  agents-local-intake.yml       → calls reusable-agents-*.yml    │
│  agents-local-orchestrator.yml → calls reusable-70-*.yml        │
│  (thin callers only - no business logic)                        │
└─────────────────────────────────────────────────────────────────┘
```

## Prerequisites

### Required Secrets

| Secret | Purpose | How to Obtain |
|--------|---------|---------------|
| `ACTIONS_BOT_PAT` | Create branches, open PRs, dispatch workflows | Create a PAT with `repo`, `workflow` scopes |
| `SERVICE_BOT_PAT` | Alternative token for service operations | Same as above, optional |

### Required Labels

Create these labels in the repository:

| Label | Color | Description |
|-------|-------|-------------|
| `agent:codex` | `#6f42c1` | Issues for Codex automation |
| `agents:codex` | `#6f42c1` | Alternative codex label |
| `status:ready` | `#0e8a16` | Issue is ready for processing |
| `status:in-progress` | `#fbca04` | Issue is being processed |
| `from:codex` | `#1d76db` | PR created by Codex automation |
| `autofix:clean` | `#c5def5` | Autofix applied cleanly |
| `agents:keepalive` | `#bfd4f2` | Enable keepalive monitoring |

### Branch Protection

Ensure branch protection allows:
- PRs from automation (bypasses or allows bot accounts)
- Workflows can push to `codex/issue-*` branches

## Implementation Phases

### Phase 1: Create Thin Caller for Issue Intake

Create a **thin caller** that references the Workflows repo reusable workflow:

```yaml
# .github/workflows/agents-63-issue-intake.yml
name: Agents 63 Issue Intake

on:
  issues:
    types: [opened, labeled, reopened, unlabeled]
  workflow_dispatch:
    inputs:
      issue_number:
        description: "Issue number to process"
        type: number

permissions:
  contents: read
  issues: write
  pull-requests: write

concurrency:
  group: issue-${{ github.event.issue.number || github.event.inputs.issue_number }}-intake
  cancel-in-progress: true

jobs:
  intake:
    # Reference the centralized reusable workflow
    uses: stranske/Workflows/.github/workflows/reusable-agents-issue-bridge.yml@main
    with:
      issue_number: ${{ github.event.inputs.issue_number || github.event.issue.number }}
    secrets:
      service_bot_pat: ${{ secrets.SERVICE_BOT_PAT }}
```

**Key point**: All the complex logic lives in `reusable-agents-issue-bridge.yml` in the Workflows repo. This file just triggers it.

### Phase 2: Create Thin Caller for Orchestrator

```yaml
# .github/workflows/agents-70-orchestrator.yml
name: Agents 70 Orchestrator

on:
  schedule:
    - cron: "*/20 * * * *"  # Every 20 minutes
  workflow_dispatch:
    inputs:
      enable_readiness:
        description: "Run readiness probes"
        type: boolean
        default: false
      enable_keepalive:
        description: "Enable keepalive sweep"
        type: boolean
        default: true
      dry_run:
        description: "Dry run mode"
        type: boolean
        default: false

permissions:
  contents: write
  issues: write
  pull-requests: write
  actions: write

jobs:
  init:
    uses: stranske/Workflows/.github/workflows/reusable-70-orchestrator-init.yml@main
    with:
      enable_readiness: ${{ inputs.enable_readiness || false }}
      enable_keepalive: ${{ inputs.enable_keepalive || true }}
    secrets: inherit

  main:
    needs: init
    if: needs.init.outputs.has_work == 'true'
    uses: stranske/Workflows/.github/workflows/reusable-70-orchestrator-main.yml@main
    with:
      params_json: ${{ needs.init.outputs.params_json }}
    secrets: inherit
```

### Phase 3: Belt Workflows (71/72/73)

The belt workflows are **not reusable** - they're specific to the Workflows repo and use `repository_dispatch`. For satellite repos, there are two options:

#### Option A: Let Workflows Repo Handle Belt (Recommended)

The orchestrator in the Workflows repo can dispatch work to satellite repos via the `repo:` field in issues. The keepalive and belt automation run from the hub.

**Pros**: Zero maintenance in satellite repos
**Cons**: Issues must reference the satellite repo explicitly

#### Option B: Duplicate Belt Locally (Advanced)

If you need fully independent automation, copy the belt workflows. But then you must:

1. **Subscribe to Workflows repo releases** to know when updates happen
2. **Manually sync** changes to satellite repos
3. **Test alignment** after each sync

This is the maintenance burden the reusable pattern avoids.

### Phase 4: Version Pinning Strategy

For stability, pin to a specific version instead of `@main`:

```yaml
# Stable: pin to release tag
uses: stranske/Workflows/.github/workflows/reusable-16-agents.yml@v1

# Specific: pin to SHA (most stable)
uses: stranske/Workflows/.github/workflows/reusable-16-agents.yml@dc46ca4

# Floating: always latest (risky but automatic updates)
uses: stranske/Workflows/.github/workflows/reusable-16-agents.yml@main
```

**Recommended**: Use `@v1` for stability, bump when new features are needed.

## Alignment Strategy

### Keeping Workflows in Sync

Since the Workflows repo is the source of truth, alignment is maintained by:

1. **Reusable workflow references**: The `uses:` syntax automatically pulls the latest (or pinned) version
2. **Version pinning**: Control updates by pinning to tags/SHAs
3. **Dependabot for workflows**: Configure Dependabot to update workflow references

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    # This will suggest PRs when stranske/Workflows updates
```

### When Alignment Breaks

If the Workflows repo makes breaking changes:

1. **If using `@main`**: Your workflows will break immediately
2. **If using `@v1`**: You're protected until you bump the version
3. **If using `@SHA`**: Maximum stability, manual bumps required

**Recommended workflow**:
1. Pin to `@v1` in production
2. Test `@main` in a feature branch
3. Bump production after validation

## Testing Plan

### Local Testing (Before Deployment)

1. **Create thin caller workflow** in `.github/workflows/`
2. **Test with `workflow_dispatch`** to manually trigger
3. **Verify secrets are configured** (`SERVICE_BOT_PAT`, `ACTIONS_BOT_PAT`)

### Integration Testing

1. Create a test issue with `agent:codex` label
2. Verify the thin caller triggers the Workflows repo reusable workflow
3. Verify issue processing works correctly

### Smoke Test Checklist

- [ ] Thin caller workflow exists
- [ ] `SERVICE_BOT_PAT` secret configured
- [ ] Manual dispatch works
- [ ] Label trigger works
- [ ] Workflows repo reusable workflow invoked successfully

## Rollout Plan

### Phase 1: Issue Intake (Week 1)
1. Create `agents-63-issue-intake.yml` thin caller
2. Configure `SERVICE_BOT_PAT` secret
3. Test with manual dispatch
4. Enable label trigger

### Phase 2: Orchestrator (Week 2)
1. Create `agents-70-orchestrator.yml` thin caller
2. Configure `ACTIONS_BOT_PAT` secret
3. Test with manual dispatch
4. Enable schedule (every 20 min)

### Phase 3: Monitoring (Week 3)
1. Monitor workflow runs
2. Adjust version pinning if needed
3. Set up Dependabot for workflow updates

## Summary: What This Repo Needs

| Item | Status | Notes |
|------|--------|-------|
| `Issues.txt` | ✅ Created | Test issues ready |
| Required labels | ⚠️ Verify | `agent:codex`, `status:ready`, etc. |
| `SERVICE_BOT_PAT` secret | ❌ Needed | For issue bridge |
| `ACTIONS_BOT_PAT` secret | ❌ Needed | For orchestrator |
| Thin caller: intake | ❌ Create | ~20 lines, references Workflows repo |
| Thin caller: orchestrator | ❌ Create | ~30 lines, references Workflows repo |

**Total new code in this repo**: ~50 lines of YAML (thin callers only)

**Maintenance burden**: Near zero - updates flow from Workflows repo

## References

- [Workflows repo USAGE.md](https://github.com/stranske/Workflows/blob/main/docs/USAGE.md)
- [ci_reuse.md](https://github.com/stranske/Workflows/blob/main/docs/ci_reuse.md)
- [Agent automation overview](https://github.com/stranske/Workflows/blob/main/docs/agent-automation.md)
- [WORKFLOWS.md](https://github.com/stranske/Workflows/blob/main/docs/ci/WORKFLOWS.md)
- [Integration guide](https://github.com/stranske/Workflows/blob/main/docs/INTEGRATION_GUIDE.md)
