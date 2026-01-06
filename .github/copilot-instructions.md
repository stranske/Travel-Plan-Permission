# Copilot Instructions for this Repository

> **Skills Loaded**: This file contains embedded skills that help with CI debugging, GitHub operations, and meta-patterns. Consult the relevant section when facing issues.

## Quick Reference - When to Apply Which Skill

| Situation | Skill Section |
|-----------|---------------|
| CI failing with mypy errors | [CI Debugging - Mypy](#mypy-type-errors) |
| CI failing with coverage errors | [CI Debugging - Coverage](#coverage-threshold-failures) |
| Adding test dependencies | [Dependency Management](#test-dependencies) |
| Need to push changes | [GitHub Operations](#standard-pr-workflow) |
| Authentication errors with `gh` | [GitHub Operations - PAT](#authentication--pat-usage) |
| Making same mistake 3+ times | [Meta - Create a Skill](#recognize-when-to-create-a-new-skill) |

---

## Skill: GitHub Operations

### Authentication & PAT Usage
- **Codespaces PAT**: When performing GitHub operations that require elevated permissions (pushing to protected branches, creating releases, etc.), always check if a `CODESPACES_PAT` or `GH_TOKEN` environment variable is available
- Use `gh auth status` to verify current authentication before operations
- If authentication fails, remind the user they may need to set up a PAT with appropriate scopes
- If GITHUB_TOKEN is set and blocking PAT usage: `unset GITHUB_TOKEN` first

### Branch Protection Rules
- **Never assume direct push to `main` is allowed** - most repos have branch protection
- Always create a feature branch first: `git checkout -b fix/descriptive-name`
- Push to the feature branch, then create a PR
- Check for existing branch protection: `gh api repos/{owner}/{repo}/branches/main/protection`

### Standard PR Workflow
1. Create a branch: `git checkout -b type/description` (types: fix, feat, chore, docs)
2. Make changes and commit with conventional commit messages
3. Push branch: `git push origin branch-name`
4. Create PR: `gh pr create --title "type: description" --body "..."`
5. Wait for CI to pass before requesting merge

---

## Skill: Dependency Management

**Trigger**: Need to add test dependencies to pyproject.toml

### Test Dependencies

**Critical Rule**: Test dependencies ALWAYS go in the `dev` extra, NEVER in a separate `test` extra.

**Why**: 
- `scripts/sync_test_dependencies.py` is hardcoded to use `DEV_EXTRA = "dev"` (line 33)
- The script's `add_dependencies_to_pyproject()` function explicitly adds to the dev group
- Lock files are regenerated with `--extra dev`, not `--extra test`
- Creating a separate `test` group breaks the automated dependency sync workflow

**Correct Structure** in `pyproject.toml`:
```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-cov>=4.0.0",
    "hypothesis>=6.0.0",
    "numpy>=1.24.0",
    "pandas>=2.0.0",
    "pyarrow>=10.0.0",
    # All test dependencies here
]
```

**WRONG - Never Do This**:
```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    # dev tools only
]
test = [
    "numpy>=1.24.0",
    "pandas>=2.0.0",
    # separate test group - BREAKS AUTOMATION
]
```

### How to Add Test Dependencies

1. **Use the automation script** (preferred):
   ```bash
   python scripts/sync_test_dependencies.py --fix
   ```

2. **Manual edits** (if absolutely necessary):
   - Add to the `[project.optional-dependencies]` `dev` array
   - NEVER create a `test` array
   - Always add to existing `dev` group

3. **After adding dependencies**:
   ```bash
   pip-compile --extra=dev -o requirements-dev.lock pyproject.toml
   ```

### Common Mistakes to Avoid

❌ Creating `[project.optional-dependencies.test]` group  
❌ Adding `version-utils` as external package (it's a local test helper at `tests/helpers/version_utils.py`)  
❌ Manual edits without running `--fix` flag  
❌ Forgetting to regenerate lock files after changes  

✅ Use `sync_test_dependencies.py --fix`  
✅ Add to existing `dev` group  
✅ Regenerate both requirements.lock and requirements-dev.lock  

### Detection Pattern

If you see in a PR review:
- "Created separate test dependency group"
- "Added version-utils as external dependency"
- "Test dependencies not in dev extra"

→ Stop and use this skill to fix the architecture

---

## Skill: CI Debugging

**Trigger**: CI is failing. Before attempting fixes, diagnose the root cause.

### Diagnostic Steps
1. Get the run ID: `gh run list --repo owner/repo --limit 1 --json databaseId`
2. Get failing job: `gh api repos/{owner}/{repo}/actions/runs/{id}/jobs | jq '.jobs[] | select(.conclusion == "failure")'`
3. Get logs: `gh run view {id} --repo owner/repo --log-failed`

### Mypy Type Errors
- If mypy fails on modules with existing type issues, add overrides to `pyproject.toml`:
  ```toml
  [[tool.mypy.overrides]]
  module = ["problematic_module.*"]
  ignore_errors = true
  ```
- **Critical**: The `exclude` pattern in mypy config only prevents direct checking, NOT imports from other modules. Use `ignore_errors = true` in overrides instead.

### Coverage Threshold Failures
- Check both `pyproject.toml` (`[tool.coverage.report] fail_under`) AND workflow files for `coverage-min` settings
- These must match or the lower one wins

### jsonschema Version Conflicts
- Pin to compatible range: `jsonschema>=4.17.3,<4.23.0`
- Version 4.23.0+ has breaking changes with referencing

### Nightly Tests Running in Regular CI
- Add `conftest.py` with pytest hook to skip `@pytest.mark.nightly` tests:
  ```python
  def pytest_collection_modifyitems(config, items):
      for item in items:
          if "nightly" in item.keywords:
              item.add_marker(pytest.mark.skip(reason="Nightly test"))
  ```

---

## Skill: Meta-Patterns

### Recognize When to Create a New Skill

**Trigger**: You've made the same type of mistake or forgotten the same pattern 3+ times.

**Rule**: If you're doing something for the third time, it should be a skill.

**Signs you need a new skill**:
- Forgot to check for PAT before GitHub operations (again)
- Forgot branch protection rules (again)
- Had to re-diagnose the same CI failure pattern
- User expressed frustration about repeated issues

**How to create a skill**:
1. Identify the trigger condition
2. Document the correct steps
3. Add common failure patterns
4. Add to the relevant section of this file

---

## Repository-Specific Notes

### Manager-Database (stranske/Manager-Database)
- Has modules with type issues: `adapters/`, `api/`, `etl/`, `embeddings.py`
- Uses Prefect 2.x - import schedules from `prefect.client.schemas.schedules`
- Coverage threshold: 75%

### Travel-Plan-Permission
- Python package in `src/travel_plan_permission/`
- Config files in `config/`
- Templates in `templates/`
