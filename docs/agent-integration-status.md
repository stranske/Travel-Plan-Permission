# Agent Workflow Integration Status

This document tracks what agent automation features from stranske/Workflows are
available in this repository and what setup is required.

## Integration Matrix

| Feature | Status | How to Use | Setup Required |
|---------|--------|------------|----------------|
| **Reusable Python CI** | ✅ Active | Automatic on PR/push | None - already configured |
| **Reusable Docker CI** | ⚪ Available | Add job calling `reusable-12-ci-docker.yml` | Add workflow job |
| **Issue-to-PR via Codex** | ✅ Active | Label issue with `agent:codex` or use issue intake | Thin callers present |
| **Keepalive monitoring** | ✅ Active | Label PR with `agents:keepalive` | `agents-80-pr-event-hub.yml` and `agents-81-gate-followups.yml` present |
| **Autofix formatting** | ✅ Active | Label PR with `autofix` | `autofix.yml` and dispatcher workflows present |
| **Full Belt automation** | ✅ Active | Use issue intake and belt thin callers | `agents-71-codex-belt-dispatcher.yml`, `agents-72-codex-belt-worker.yml`, `agents-73-codex-belt-conveyor.yml`, `agents-80-pr-event-hub.yml`, and `agents-81-gate-followups.yml` present |

## Labels Available

All required labels have been created:

### Agent Assignment
- `agent:codex` - Assign to Codex agent
- `agent:copilot` - Assign to Copilot agent (alternate)

### Agent Control
- `agents` - General agent-related label
- `agents:keepalive` - Enable keepalive monitoring
- `agents:paused` - Pause keepalive on specific PR

### Status Tracking
- `status:ready` - Issue ready for agent pickup
- `status:in-progress` - Work in progress

### Automation
- `autofix` - Request automatic formatting fixes
- `autofix:clean` - Autofix found no issues
- `from:codex` - PR was created by Codex

## Current Workflow

### What Works Now

1. **Create an issue** in this repo with the appropriate agent label or issue-intake format
2. **Issue intake and belt workflows** route work through the thin callers
3. **Label PR** with `agents:keepalive` and `autofix` for monitoring and formatting recovery
4. **CI runs** automatically via reusable and repo-local workflows
5. **PR event hub and gate followups** keep the PR moving after gate events

### What Requires Workflows Repo

The reusable agent belt implementation still lives in the Workflows repo, while
this repo invokes it through thin caller workflows. To update belt behavior:

1. **Issues.txt pattern**: Create issues in Workflows repo using Issues.txt
2. **Orchestrator**: Run from Workflows repo Actions tab
3. **Keepalive sweeps**: Triggered by Workflows repo scheduler

## Connecting to Workflows Repo Agent System

### Option 1: Minimal (Current Setup)

Use GitHub's native Codex integration:
- Create issues with `agent:codex` label
- Codex responds directly to @mentions
- Manual PR management

**Pros**: Simple, no additional setup
**Cons**: No automated keepalive, no belt automation

### Option 2: Reference from Workflows Repo

Create issues in the Workflows repo that reference this repo:
- Use Issues.txt in Workflows repo
- Include repo reference in issue body
- Orchestrator can dispatch work

**Pros**: Full automation available
**Cons**: Issues live in different repo

### Option 3: Thin Caller Workflows (Active Full Automation)

Create **thin caller workflows** that reference the Workflows repo reusable workflows:

```yaml
# .github/workflows/agents-63-issue-intake.yml
uses: stranske/Workflows/.github/workflows/reusable-agents-issue-bridge.yml@main
```

**Pros**: Full automation, automatic updates from Workflows repo, minimal maintenance
**Cons**: Requires configured secrets (`SERVICE_BOT_PAT`, `ACTIONS_BOT_PAT`)

## Recommended Approach

For this project, **Option 3 (Thin Callers)** is active:

1. ✅ Labels are set up
2. ✅ Reusable CI works
3. ✅ Issues can be assigned to agents or routed by issue intake
4. ✅ Belt dispatcher, worker, conveyor, PR hub, gate followups, verifier, and autofix workflows are present

See [belt-automation-plan.md](./belt-automation-plan.md) for the reusable workflow pattern.

## Agents 63 Access

**Can you access Agents 63 here?** Not directly in the current setup.

### What is Agents 63?

`agents-63-issue-intake.yml` is the workflow in the Workflows repo that:
- Watches for new issues with `agent:codex` label
- Parses Issues.txt format
- Creates GitHub issues with proper labels
- Feeds into the belt automation pipeline (71→72→73)

### How to Access Agents 63 Functionality

**Option A: Create issues via Workflows repo** (Simplest)
1. Add your issue to `Issues.txt` in the Workflows repo
2. Reference this repo in the issue body: `repo: stranske/Travel-Plan-Permission`
3. The orchestrator will dispatch work to this repo

**Option B: Use native GitHub Codex** (Current)
1. Create issue directly in this repo
2. Add `agent:codex` label
3. @mention the agent in comments
4. No automatic intake, but agent responds to mentions

**Option C: Duplicate agents-63 locally** (See belt-automation-plan.md)
1. Copy `agents-63-issue-intake.yml` to this repo
2. Create local `Issues.txt` (✅ already done)
3. Set up required secrets (SERVICE_BOT_PAT)
4. Full local automation

### Current Status

| Feature | Status | Notes |
|---------|--------|-------|
| `Issues.txt` | ✅ Ready | Two test issues created |
| `agents-issue-intake` workflow | ✅ Active | Thin caller present locally |
| `agent:codex` label | ✅ Ready | Can create issues with this label |
| Secrets for automation | ✅ Configured | Thin callers can use repo automation secrets |

### Quick Start for Agent Work

To start using agents in this repo today:

```bash
# 1. Create an issue with the proper format (see Issues.txt for examples)
# 2. Add label: agent:codex
# 3. Mention the agent:
@codex please work on this issue
```

For full belt automation, see [belt-automation-plan.md](./belt-automation-plan.md).

## Using Agent Labels

### Creating an Agent Issue

```markdown
## Why
Brief explanation of the need.

## Scope
- What's included
- What's excluded

## Tasks
- [ ] Task 1
- [ ] Task 2

## Acceptance criteria
- [ ] AC 1
- [ ] AC 2
```

Then add label: `agent:codex`

### Activating Agent on PR

Comment on the PR:
```
@codex please review this PR and suggest improvements
```

### Enabling Keepalive

Add label `agents:keepalive` to the PR.

When using manual keepalive, periodically comment:
```
@codex please continue working on the remaining tasks
```

## Secrets Required

For full agent automation (if implemented):

| Secret | Purpose | Required for |
|--------|---------|--------------|
| `SERVICE_BOT_PAT` | Bot account operations | Keepalive posting |
| `OWNER_PR_PAT` | PR creation with elevated permissions | Belt worker |
| `ACTIONS_BOT_PAT` | Workflow dispatch | Belt dispatcher |

Currently not required for minimal setup.

## Future Enhancements

1. **Add autofix workflow** - Copy `autofix.yml` for automatic formatting
2. **Add issue intake** - Local version of `agents-63-issue-intake.yml`
3. **Add PR meta manager** - Track issue→PR relationships
4. **Full belt automation** - Complete pipeline duplication

## References

- [CI System Guide](./ci-system-guide.md) - Full CI documentation
- [Agent Automation Overview](https://github.com/stranske/Workflows/blob/main/docs/agent-automation.md)
- [Keepalive Documentation](https://github.com/stranske/Workflows/blob/main/docs/keepalive/GoalsAndPlumbing.md)
- [Issue Format Guide](https://github.com/stranske/Workflows/blob/main/docs/ci/ISSUE_FORMAT_GUIDE.md)
