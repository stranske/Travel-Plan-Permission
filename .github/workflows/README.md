# Workflow Architecture

This repository uses a **standalone CI approach** with self-contained workflows
optimized for this project's specific needs.

For comprehensive documentation, see [docs/ci-system-guide.md](../../docs/ci-system-guide.md).

## Workflow Files

| File | Purpose | Description |
|------|---------|-------------|
| `ci.yml` | Main CI pipeline | Python testing (3.11, 3.12), linting with ruff, type checking with mypy |
| `lint.yml` | Additional linting | actionlint, JSON schema validation, docs link checking |
| `agents-*.yml` | Agent automation | Issue intake and automation workflows |
| `maint-*.yml` | Maintenance | Dependency refresh and other maintenance tasks |

## Archived Workflows

The following workflows have been archived to `.github/workflows-archive/`:

| File | Reason |
|------|--------|
| `labeler.yml` | PR auto-labeling provided marginal value; labels not used by CI gates |

## CI Jobs

### ci.yml

| Job | Description |
|-----|-------------|
| `test` | Matrix job running pytest on Python 3.11 and 3.12 with coverage |
| `lint` | Runs ruff to check code style |

### lint.yml

| Job | Description |
|-----|-------------|
| `actionlint` | Validates GitHub Actions workflow syntax |
| `docs-lint` | Checks documentation links |
| `schema-validate` | Validates JSON schema files |

## Configuration

Tool versions are pinned in `autofix-versions.env` for consistency between
local development and CI:

```bash
RUFF_VERSION=0.8.4
MYPY_VERSION=1.13.0
PYTEST_VERSION=8.3.4
# ... see file for full list
```

## Secrets

| Secret | Used by | Purpose |
|--------|---------|---------|
| `GITHUB_TOKEN` | All jobs | Default token, auto-provided |

## References

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [ruff Documentation](https://docs.astral.sh/ruff/)
- [pytest Documentation](https://docs.pytest.org/)
