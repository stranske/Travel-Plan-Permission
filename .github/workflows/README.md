# Workflow Architecture

This repository uses a **hybrid CI approach** combining local domain-specific
jobs with reusable workflows from [stranske/Workflows](https://github.com/stranske/Workflows).

For comprehensive documentation, see [docs/ci-system-guide.md](../../docs/ci-system-guide.md).

## Current Pin

| Repository | Ref | SHA | Updated |
|------------|-----|-----|---------|
| stranske/Workflows | main | `dc46ca4fa721e31df650e999d0fe108da7e4574c` | 2024-12-22 |

### Updating the pin

```bash
# Get latest SHA
gh api repos/stranske/Workflows/commits/main --jq '.sha'

# Update ci.yml header comment and python-ci job reference
```

## Workflow Files

| File | Purpose | Type |
|------|---------|------|
| `ci.yml` | Main CI pipeline (lint, schema validation, gate) | Hybrid |
| `labeler.yml` | Auto-label PRs based on paths | Local |

## Job Responsibilities

### Local Jobs (domain-specific)

These jobs contain logic unique to Travel-Plan-Permission and are maintained
in this repository:

| Job | What it validates | Why local |
|-----|-------------------|-----------|
| `docs-lint` | Markdown formatting, link integrity | Travel-specific documentation standards |
| `schema-validate` | JSON Schema (trip_plan, expense_report) | Domain schemas unique to this project |

### Reusable Jobs (from stranske/Workflows)

These jobs call reusable workflows for standard language CI:

| Job | Workflow | When to enable |
|-----|----------|----------------|
| `python-ci` | `reusable-10-ci-python.yml` | When Python implementation code is added |

## Adding Python CI

When Stage 1 (Excel Agent Bridge) or later stages add Python code:

1. Uncomment the `python-ci` job in `ci.yml`
2. Add `python-ci` to the `gate` job's `needs` array
3. Configure inputs as needed:

```yaml
python-ci:
  name: Python CI
  uses: stranske/Workflows/.github/workflows/reusable-10-ci-python.yml@dc46ca4...
  with:
    python-versions: '["3.11", "3.12"]'
    coverage-min: "80"
    working-directory: "src"  # if code is in a subdirectory
  secrets: inherit
```

## Secrets

| Secret | Used by | Purpose |
|--------|---------|---------|
| `GITHUB_TOKEN` | All jobs | Default token, auto-provided |

Additional secrets may be needed when Python CI is enabled (e.g., `CODECOV_TOKEN`
for coverage reporting).

## Troubleshooting

### Workflow not found

If GitHub can't find a reusable workflow:
- Verify the SHA exists: `gh api repos/stranske/Workflows/commits/<sha>`
- Check that stranske/Workflows is public (or configure PAT if private)

### Permission denied

Ensure workflow has required permissions. Current `ci.yml` uses minimal:
```yaml
permissions:
  contents: read
```

For Python CI with coverage comments, you may need:
```yaml
permissions:
  contents: read
  pull-requests: write
```

## References

- [stranske/Workflows Integration Guide](https://github.com/stranske/Workflows/blob/main/docs/INTEGRATION_GUIDE.md)
- [Reusable CI Documentation](https://github.com/stranske/Workflows/blob/main/docs/ci_reuse.md)
- [GitHub Reusable Workflows](https://docs.github.com/en/actions/using-workflows/reusing-workflows)
