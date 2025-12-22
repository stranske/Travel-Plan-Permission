# CI System Guide

This document describes the CI/CD system for Travel-Plan-Permission and how it
integrates with the [stranske/Workflows](https://github.com/stranske/Workflows)
repository for reusable automation.

## Table of Contents

1. [Overview](#overview)
2. [Workflows Repository Capabilities](#workflows-repository-capabilities)
3. [Local CI Configuration](#local-ci-configuration)
4. [Agent Automation System](#agent-automation-system)
5. [Troubleshooting](#troubleshooting)
6. [Quick Reference](#quick-reference)

---

## Overview

This repository uses a **hybrid CI approach**:

- **Local jobs**: Domain-specific validation (JSON schemas, markdown docs)
- **Reusable workflows**: Standard language CI from stranske/Workflows

```
┌─────────────────────────────────────────────────────────────┐
│                    Travel-Plan-Permission                    │
│                        .github/workflows/ci.yml              │
├─────────────────────────────────────────────────────────────┤
│  Local Jobs                │  Reusable Workflows            │
│  ─────────────────         │  ────────────────────────────  │
│  • actionlint              │  • python-ci                   │
│  • docs-lint               │    (reusable-10-ci-python.yml) │
│  • schema-validate         │                                │
├─────────────────────────────────────────────────────────────┤
│                           Gate                               │
│              Aggregates all job results                      │
└─────────────────────────────────────────────────────────────┘
```

---

## Workflows Repository Capabilities

The [stranske/Workflows](https://github.com/stranske/Workflows) repository
provides:

### Reusable CI Workflows

| Workflow | Purpose | Usage |
|----------|---------|-------|
| `reusable-10-ci-python.yml` | Python lint (ruff), type check (mypy), test (pytest), coverage | Used by this repo |
| `reusable-11-ci-node.yml` | Node.js lint, format, type check, test | Available if needed |
| `reusable-12-ci-docker.yml` | Docker build + smoke test | Available if needed |
| `reusable-18-autofix.yml` | Automated code formatting fixes | Used with autofix label |

### Agent Automation System

The Workflows repo includes a sophisticated agent automation system:

| Component | Purpose |
|-----------|---------|
| **Agents 63 Issue Intake** | Converts labeled issues into agent work items |
| **Agents 70 Orchestrator** | Central control for readiness, bootstrap, keepalive |
| **Agents 71-73 Codex Belt** | Dispatcher → Worker → Conveyor pipeline for PRs |
| **Keepalive System** | Monitors stalled agent PRs and nudges them |
| **Autofix** | Automatic formatting fixes on PRs |

### Key Features

- **Readiness probes**: Validates agent availability before work
- **Bootstrap**: Creates branches and PRs from labeled issues
- **Keepalive**: Monitors agent PRs and posts reminder comments
- **Conveyor**: Auto-merges successful PRs and cleans up
- **Watchdog**: Detects stalled automation

---

## Local CI Configuration

### Current Jobs

| Job | Purpose | Runs On |
|-----|---------|---------|
| `actionlint` | Validates workflow YAML syntax | Every PR/push |
| `docs-lint` | Markdown formatting + link validation | Every PR/push |
| `schema-validate` | JSON Schema compilation + fixture validation | Every PR/push |
| `python-ci` | Full Python CI (ruff, mypy, pytest, coverage) | Every PR/push |
| `gate` | Aggregates all results for branch protection | Every PR/push |

### Adding New Local Jobs

To add a domain-specific job:

1. Add the job definition in `.github/workflows/ci.yml`
2. Add the job name to the `gate` job's `needs` array
3. Update `gate`'s result logging step

### Customizing Python CI

The `python-ci` job accepts these inputs:

```yaml
python-ci:
  uses: stranske/Workflows/.github/workflows/reusable-10-ci-python.yml@<sha>
  with:
    python-versions: '["3.11", "3.12"]'  # Version matrix
    coverage-min: "80"                    # Minimum coverage %
    working-directory: "."                # For monorepos
    marker: "not slow"                    # pytest marker filter
  secrets: inherit
```

---

## Agent Automation System

### How Agent Automation Works

```
1. Issue created with `agent:codex` label
   ↓
2. Agents 63 Issue Intake detects the label
   ↓
3. Issue Bridge creates branch + PR
   ↓
4. Codex Belt Worker activates the agent
   ↓
5. Agent works on the PR
   ↓
6. Keepalive monitors progress, nudges if stalled
   ↓
7. Gate passes → Conveyor auto-merges
   ↓
8. Issue closed, branch deleted
```

### Using Issues.txt Pattern

The Workflows repo uses an `Issues.txt` file to batch-create issues:

```
1) Issue title here
Labels: agent:codex, enhancement
Why
Explanation of the problem or need.
Scope
- What's included
- What's excluded
Tasks
- [ ] Task 1
- [ ] Task 2
Acceptance criteria
- [ ] Criterion 1
- [ ] Criterion 2
Implementation notes
- Technical details

2) Next issue title
...
```

**To use this pattern:**

1. Create/update `Issues.txt` in the Workflows repo
2. Run `agents-63-issue-intake.yml` workflow (manual dispatch)
3. Issues are created on the GitHub Issues tab
4. Label issues with `agent:codex` to trigger automation

### Required Labels

For agent automation to work, these labels must exist:

| Label | Purpose | Required for |
|-------|---------|--------------|
| `agent:codex` | Marks issue for Codex agent | Bootstrap |
| `agents:keepalive` | Enables keepalive monitoring | Keepalive |
| `autofix` | Enables automatic formatting | Autofix |
| `status:ready` | Issue ready for agent pickup | Belt dispatcher |
| `status:in-progress` | Issue being worked | Belt tracking |

### What Works Now vs. What Needs Setup

| Feature | Status | Notes |
|---------|--------|-------|
| Reusable Python CI | ✅ Works | Just `uses:` the workflow |
| Reusable Docker CI | ✅ Works | Just `uses:` the workflow |
| Issue creation from Issues.txt | ⚠️ Workflows repo only | Issues created there |
| Agent bootstrap (branch/PR) | ⚠️ Needs labels | Must have correct labels |
| Keepalive monitoring | ⚠️ Needs labels + PR | Label PRs with `agents:keepalive` |
| Autofix | ⚠️ Needs workflow + labels | Copy autofix workflow or call reusable |
| Full Belt automation | ❌ Needs duplication | Complex; requires local workflows |

### Minimal Agent Integration

For basic agent support without full belt automation:

1. **Ensure labels exist** (see [Creating Labels](#creating-labels))
2. **Create issues with proper labels**
3. **Label PRs** for keepalive and autofix

The Workflows repo's orchestrator and belt workflows operate within that repo.
To have similar automation here, you would need to:

- Copy relevant workflow files
- Adjust repository references
- Configure required secrets (PATs)

---

## Troubleshooting

### CI Failures

#### Python CI Fails

**Symptoms**: `python-ci` job fails

**Common causes**:
- Linting errors (ruff) → Run `ruff check --fix src/ tests/`
- Type errors (mypy) → Fix type annotations
- Test failures → Check test output, fix failing tests
- Coverage below threshold → Add more tests

**Debug locally**:
```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run linting
ruff check src/ tests/python/

# Run type checking
mypy src/ tests/python/

# Run tests with coverage
pytest tests/python/ --cov=src --cov-report=term-missing
```

#### Schema Validation Fails

**Symptoms**: `schema-validate` job fails

**Common causes**:
- Invalid JSON in schema files
- Fixtures don't match schema
- Schema syntax errors

**Debug locally**:
```bash
npm ci
npx ajv compile --spec=draft2020 -c ajv-formats -s schemas/trip_plan.min.schema.json
npx ajv validate --spec=draft2020 -c ajv-formats \
  -s schemas/trip_plan.min.schema.json \
  -d tests/fixtures/sample_trip_plan_minimal.json
```

#### Docs Lint Fails

**Symptoms**: `docs-lint` job fails

**Common causes**:
- Markdown formatting issues
- Broken links

**Debug locally**:
```bash
npx markdownlint-cli2 "**/*.md" "!**/node_modules/**"
```

### Workflow Errors

#### "Workflow not found"

**Cause**: Invalid ref or workflow path

**Fix**: Verify the SHA exists:
```bash
gh api repos/stranske/Workflows/commits/<sha>
```

#### "Permission denied"

**Cause**: Missing permissions or secrets

**Fix**: Check workflow permissions block and ensure secrets are configured

#### Reusable workflow fails to start

**Cause**: Network issues or GitHub outage

**Fix**: Re-run the workflow; check [GitHub Status](https://www.githubstatus.com/)

### Agent Automation Issues

#### "No labelled issues found"

**Cause**: Missing or incorrect labels on issues

**Fix**: Ensure issue has exactly one `agent:*` label

#### "Bootstrap skipped"

**Cause**: No issues match `bootstrap_issues_label`

**Fix**: Add the required label to issues

#### Keepalive not triggering

**Cause**: Missing `agents:keepalive` label on PR

**Fix**: Add label to the PR

---

## Quick Reference

### Updating the Workflows Pin

```bash
# Get latest SHA
gh api repos/stranske/Workflows/commits/main --jq '.sha'

# Update in ci.yml:
# 1. Header comment
# 2. WORKFLOWS_REF env var
# 3. python-ci uses: line
```

### Running CI Locally

```bash
# Full validation
pip install -e ".[dev]"
ruff check src/ tests/python/
mypy src/ tests/python/
pytest tests/python/ --cov=src --cov-report=term-missing
npm ci
npx ajv compile --spec=draft2020 -c ajv-formats -s schemas/*.json
npx markdownlint-cli2 "**/*.md" "!**/node_modules/**"
```

### Creating Labels

```bash
# Create a single label
gh label create "agent:codex" --color "7057ff" --description "Codex agent assignment"

# Create multiple labels (see docs/labels.md for full list)
```

### Useful Links

- [Workflows Integration Guide](https://github.com/stranske/Workflows/blob/main/docs/INTEGRATION_GUIDE.md)
- [CI Workflow Documentation](https://github.com/stranske/Workflows/blob/main/docs/ci-workflow.md)
- [Agent Automation Overview](https://github.com/stranske/Workflows/blob/main/docs/agent-automation.md)
- [Issue Format Guide](https://github.com/stranske/Workflows/blob/main/docs/ci/ISSUE_FORMAT_GUIDE.md)
- [Keepalive Documentation](https://github.com/stranske/Workflows/blob/main/docs/keepalive/GoalsAndPlumbing.md)
