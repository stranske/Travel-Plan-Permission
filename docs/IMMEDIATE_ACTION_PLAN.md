# Immediate Action Plan: Fix Dependabot Version Test Issues

**Date:** 2026-01-05  
**Priority:** URGENT  
**Primary Issue:** Trend_Model_Project PR #4214 failing due to lock file drift

---

## 🔥 Immediate Actions (Fix PR #4214)

### 1. Fix Lock File Sync (5 minutes)

```bash
# Clone and checkout the PR branch
gh pr checkout 4214 --repo stranske/Trend_Model_Project

# Regenerate lock file
uv pip compile pyproject.toml --output-file requirements.lock

# Commit and push
git add requirements.lock
git commit -m "chore: sync lock file with numpy 2.4.0 update"
git push
```

**This will unblock the PR and allow CI to pass.**

---

## 📋 Today's Tasks (High Priority)

### 2. Refactor Hardcoded Version Test (1 hour)

**File:** `Trend_Model_Project/tests/test_llm_dependency_compatibility.py`

**Current Problem:**
```python
# ❌ HARDCODED - breaks every dependency update
expected_ranges = {
    "langchain": (1, 2),
    "langchain-core": (1, 2),
    "langchain-community": (0, 4),
}
```

**Solution:**
Replace with dynamic extraction from pyproject.toml:

```python
import tomllib
from packaging.version import Version
from packaging.specifiers import SpecifierSet

def get_declared_range(package: str) -> SpecifierSet:
    """Extract version range from pyproject.toml."""
    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    
    for dep in data["project"]["dependencies"]:
        if dep.startswith(package):
            # Parse "langchain>=1.2,<1.3" -> SpecifierSet
            spec_str = dep.split(package, 1)[1]
            return SpecifierSet(spec_str.strip())
    
    return SpecifierSet()

def test_langchain_versions_match_pyproject(distribution: str) -> None:
    """Validate installed version matches pyproject.toml range."""
    installed = Version(importlib.metadata.version(distribution))
    declared = get_declared_range(distribution)
    
    assert installed in declared, (
        f"{distribution} version {installed} not in declared range {declared}"
    )
```

### 3. Add Lock File Automation (30 minutes)

**Create:** `.github/workflows/dependabot-auto-lock.yml`

This workflow automatically regenerates lock files when Dependabot updates pyproject.toml.

**Template available at:**
`Travel-Plan-Permission/.github/workflows/dependabot-auto-lock.yml`

**Key points:**
- Runs only for Dependabot PRs
- Uses `CODESPACES` PAT to push to protected branches
- Comments on PR when lock files are updated

---

## 📅 This Week (Medium Priority)

### 4. Enable Dependabot (If Not Already Enabled)

**File:** `.github/dependabot.yml`

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
    groups:
      runtime-minor:
        patterns: ["*"]
        update-types: ["minor", "patch"]
    open-pull-requests-limit: 10
```

### 5. Run Audit on All Repos

```bash
# For each consumer repo:
cd /path/to/repo
python scripts/audit_version_tests.py --fix
```

**Repos to audit:**
1. ✅ Travel-Plan-Permission (reference implementation - no issues found)
2. ⚠️ Trend_Model_Project (known issues)
3. ❓ Manager-Database
4. ❓ trip-planner
5. ❓ Portable-Alpha-Extension-Model

### 6. Copy Helper Files to Trend_Model_Project

**Files to copy:**
1. `tests/helpers/version_utils.py` - Version testing utilities
2. `tests/python/test_dependency_version_patterns.py` - Reference patterns
3. `.github/workflows/dependabot-auto-lock.yml` - Auto-lock workflow
4. `scripts/git-hooks/pre-commit` - Pre-commit hook (optional)

---

## 🎯 Success Metrics

**Immediate (Today):**
- [ ] PR #4214 CI passing (lock file fixed)
- [ ] Hardcoded version test refactored

**This Week:**
- [ ] Lock file automation deployed to Trend_Model_Project
- [ ] Dependabot enabled (if not already)
- [ ] Audit completed for 3+ repos

**This Month:**
- [ ] All consumer repos have lock file automation
- [ ] <5% of Dependabot PRs require manual intervention
- [ ] No hardcoded version assertions in any repo

---

## 🔧 Tools & Resources

### Scripts Available
- `scripts/audit_version_tests.py` - Scan for hardcoded versions
- `scripts/git-hooks/pre-commit` - Auto-regenerate lock files
- `tests/helpers/version_utils.py` - Testing utilities

### Documentation
- `docs/DEPENDENCY_VERSION_TEST_STRATEGY.md` - Full strategy guide
- `tests/python/test_dependency_version_patterns.py` - Reference examples

### PAT Token
- Environment variable: `CODESPACES`
- Used for: Pushing to Dependabot branches

---

## 📞 Questions to Resolve

### Q1: Lock File Tool
**Current state:** Mixed usage (uv, pip-tools)  
**Recommendation:** Standardize on `uv` (faster, better resolution)  
**Decision needed:** Confirm uv as standard

### Q2: Auto-Merge Strategy
**Options:**
- A: Auto-merge minor/patch after CI passes ✅ Recommended
- B: Manual review all updates
- C: Auto-merge with post-merge monitoring

**Decision needed:** Choose option A, B, or C

### Q3: Shared Test Utilities
**Where should version_utils.py live?**
- A: Copy to each repo (simpler, more duplication)
- B: Shared package in Workflows repo ✅ Recommended
- C: Separate pytest plugin package

**Decision needed:** Choose A or B (C is overkill)

---

## 📝 Command Reference

### Quick Fixes

```bash
# Fix lock file drift
uv pip compile pyproject.toml --output-file requirements.lock

# Run audit
python scripts/audit_version_tests.py --repo /path/to/repo --fix

# Test locally
pytest tests/python/test_dependency_version_patterns.py -v

# Check PR status
gh pr checks 4214 --repo stranske/Trend_Model_Project
```

### Working with PAT

```bash
# Use CODESPACES PAT for git operations
unset GITHUB_TOKEN  # If set, it blocks PAT usage
export GH_TOKEN="$CODESPACES"

# Push to Dependabot branch
git push origin HEAD
```

---

## 🎬 Next Steps

1. **Right now:** Fix PR #4214 lock file (5 min)
2. **Today:** Refactor hardcoded test (1 hour)
3. **This week:** Add automation + audit other repos
4. **Answer questions:** Lock tool, auto-merge, shared utilities

**Need help with any step? Let me know which part to tackle first!**
