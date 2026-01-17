# Workflow Alignment Status

This document explains the workflow alignment between this repository and the
central Workflows repository.

## Sync Categories

### Synced Workflows (auto-updated)
The following workflows are automatically synced from the Workflows repository
and should match exactly:
- `autofix.yml`
- `agents-*.yml` (most agent workflows)
- `dependabot-automerge.yml`
- `maint-coverage-guard.yml`
- `reusable-pr-context.yml`

### Create-Only Workflows (customizable)
The following workflows were initially created from templates but can be
customized for this repository:
- `pr-00-gate.yml` - Extended with orchestration tests
- `ci.yml` - Customized for repo-specific CI needs

### Repo-Specific Workflows
The following workflows are unique to this repository:
- `agents-63-issue-intake.yml` - Legacy intake workflow
- `agents-70-orchestrator.yml` - Legacy orchestrator
- `agents-chatgpt-sync.yml` / `agents-chatgpt-sync-test.yml` - ChatGPT integration
- `auto-merge-docs.yml` - Documentation auto-merge
- `maint-51-dependency-refresh.yml` - Dependency refresh maintenance
- `maint-dependabot-auto-lock.yml` - Dependabot lock file maintenance
- `maint-sync-workflows.yml` - Workflow synchronization

## Alignment Verification

Run the audit script to check alignment:
```bash
python scripts/audit_workflow_alignment.py --local .github/workflows \
  --workflows /path/to/Workflows/templates/consumer-repo/.github/workflows \
  --comment
```

Note: The audit will report `pr-00-gate.yml` as "modified" - this is expected
because it's a create-only workflow with legitimate customizations.
