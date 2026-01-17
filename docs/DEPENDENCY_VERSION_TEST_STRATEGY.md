# Dependency Version Test Strategy

**Status:** Planning Document  
**Created:** 2026-01-05  
**Problem:** Tests with hardcoded dependency version assertions fail en masse when Dependabot updates occur  
**Scope:** Cross-repo standardization for sustainable dependency management

---

## Problem Statement

### Current State
Tests in consumer repos (notably `Trend_Model_Project`) contain hardcoded version assertions that break when dependencies are updated:

```python
# ❌ ANTI-PATTERN: Hardcoded version expectations
expected_ranges = {
    "langchain": (1, 2),           # Breaks when langchain updates to 1.3.x
    "langchain-core": (1, 2),      # Breaks when updates to 1.3.x
    "langchain-community": (0, 4),  # Breaks when updates to 0.5.x
}
```

### Impact
- **Every Dependabot PR fails** until tests are manually updated
- Manual intervention required for routine dependency updates
- Slows down security patches and feature updates
- Creates maintenance toil across multiple repos

### Root Causes
1. **Lock file drift**: `requirements.lock`/`uv.lock` not regenerated with dependency updates
2. **Hardcoded test assertions**: Version checks assume specific major.minor versions
3. **Missing automation**: No sync between `pyproject.toml` ranges and test expectations
4. **Lack of patterns**: No established best practices for version-agnostic testing

---

## Solution Framework

### Principle: Test Behavior, Not Versions

**Core Philosophy:**
- ✅ Test that dependencies work correctly (behavior)
- ✅ Test that version ranges are *satisfiable*
- ❌ Don't assert specific version numbers
- ❌ Don't fail tests when versions bump within allowed ranges

### Strategy Tiers

#### Tier 1: Eliminate Hardcoded Versions
**Goal:** Remove version assertions that don't add value

**Pattern: Version Compatibility Tests**
```python
# ❌ BAD: Fails when minor version increments
def test_langchain_version():
    assert (major, minor) == (1, 2)

# ✅ GOOD: Tests compatibility within declared range
def test_langchain_version():
    version = importlib.metadata.version("langchain")
    # Parse range from pyproject.toml
    declared_range = get_declared_version_range("langchain")
    assert version_in_range(version, declared_range)
```

#### Tier 2: Dynamic Version Extraction
**Goal:** Derive expected versions from `pyproject.toml` at runtime

**Implementation:**
```python
import tomllib
from packaging.specifiers import SpecifierSet
from packaging.version import Version

def get_declared_version_range(package: str) -> SpecifierSet:
    """Extract version range from pyproject.toml."""
    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    
    # Search dependencies and optional-dependencies
    for dep in data.get("project", {}).get("dependencies", []):
        if dep.startswith(package):
            # Parse "langchain>=1.2,<1.3" -> SpecifierSet(">=1.2,<1.3")
            return parse_specifier(dep)
    
    return SpecifierSet()

def test_dependency_within_range():
    """Validate installed version matches declared range."""
    installed = Version(importlib.metadata.version("langchain"))
    declared = get_declared_version_range("langchain")
    
    assert installed in declared, (
        f"Installed {installed} not in declared range {declared}"
    )
```

#### Tier 3: Behavior-First Testing
**Goal:** Focus on functionality, not version numbers

**Pattern: Feature Detection**
```python
# ❌ BAD: Version-based assumptions
def test_langchain_streaming():
    if langchain_version >= (1, 2):
        assert hasattr(llm, "stream")

# ✅ GOOD: Direct feature testing
def test_langchain_streaming():
    """Streaming should be available in all supported versions."""
    assert hasattr(llm, "stream"), "Streaming API missing"
    
    # Test behavior
    result = list(llm.stream("test"))
    assert len(result) > 0
```

**Pattern: Compatibility Matrix**
```python
@pytest.mark.parametrize("feature,min_version", [
    ("stream", "1.0.0"),
    ("async_invoke", "1.1.0"),
])
def test_feature_availability(feature, min_version):
    """Features should be available when version requirement is met."""
    installed = Version(importlib.metadata.version("langchain"))
    
    if installed >= Version(min_version):
        assert hasattr(llm, feature), f"{feature} missing in {installed}"
```

#### Tier 4: Lock File Automation
**Goal:** Prevent lock file drift

**Approaches:**

1. **Pre-commit hook** (recommended for development):
```bash
#!/bin/bash
# .git/hooks/pre-commit
if git diff --cached --name-only | grep -q "pyproject.toml"; then
    echo "pyproject.toml changed, regenerating lock file..."
    make lock || exit 1
    git add requirements.lock uv.lock
fi
```

2. **CI enforcement** (required for PRs):
```yaml
# .github/workflows/ci.yml
- name: Check lock file sync
  run: |
    uv pip compile pyproject.toml --output-file requirements.check
    diff requirements.lock requirements.check || {
      echo "❌ Lock file out of sync with pyproject.toml"
      echo "Run: make lock"
      exit 1
    }
```

3. **Dependabot automation** (automatic for Dependabot PRs):
```yaml
# .github/workflows/dependabot-auto-lock.yml
name: Dependabot Auto-Lock
on:
  pull_request:
    branches: [main]
    paths: ['pyproject.toml']

jobs:
  regenerate-lock:
    if: github.actor == 'dependabot[bot]'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.head_ref }}
          token: ${{ secrets.DEPENDABOT_PAT }}
      
      - name: Regenerate lock file
        run: |
          pip install uv
          make lock
      
      - name: Commit lock file
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add requirements.lock uv.lock
          git commit -m "chore: regenerate lock files for dependency updates" || exit 0
          git push
```

---

## Test Patterns Catalog

### Pattern 1: Version Range Compliance
**Use Case:** Ensure installed versions match declared constraints

```python
def test_all_dependencies_within_declared_ranges():
    """All installed packages should satisfy pyproject.toml ranges."""
    with open("pyproject.toml", "rb") as f:
        pyproject = tomllib.load(f)
    
    all_deps = pyproject["project"]["dependencies"]
    for group in pyproject["project"].get("optional-dependencies", {}).values():
        all_deps.extend(group)
    
    failures = []
    for dep_spec in all_deps:
        name = dep_spec.split("[")[0].split("=")[0].split(">")[0].split("<")[0]
        try:
            installed = Version(importlib.metadata.version(name))
            declared = parse_specifier(dep_spec)
            if installed not in declared:
                failures.append(f"{name}: {installed} not in {declared}")
        except importlib.metadata.PackageNotFoundError:
            # Optional dependency not installed
            pass
    
    assert not failures, "\n".join(failures)
```

### Pattern 2: Breaking Change Detection
**Use Case:** Alert when dependencies introduce breaking changes

```python
def test_numpy_api_stability():
    """Test critical NumPy APIs remain available."""
    import numpy as np
    
    # These APIs must exist in all supported numpy versions
    required_apis = [
        "ndarray",
        "array",
        "zeros",
        "ones",
        "concatenate",
        "mean",
        "std",
    ]
    
    missing = [api for api in required_apis if not hasattr(np, api)]
    assert not missing, f"NumPy APIs missing: {missing}"
```

### Pattern 3: Version-Gated Features
**Use Case:** Handle optional features based on actual capabilities

```python
from packaging.version import Version
import importlib.metadata

def has_feature(package: str, feature: str, min_version: str) -> bool:
    """Check if a feature is available based on package version."""
    try:
        installed = Version(importlib.metadata.version(package))
        return installed >= Version(min_version)
    except importlib.metadata.PackageNotFoundError:
        return False

def test_streamlit_features():
    """Test streamlit features available in installed version."""
    import streamlit as st
    
    # Always available
    assert hasattr(st, "write")
    assert hasattr(st, "button")
    
    # Version-gated (example)
    if has_feature("streamlit", "container", "1.0.0"):
        assert hasattr(st, "container")
```

### Pattern 4: Compatibility Fixtures
**Use Case:** Skip tests that require specific version features

```python
import pytest
from packaging.version import Version
import importlib.metadata

def get_version(package: str) -> Version:
    """Get installed version of a package."""
    return Version(importlib.metadata.version(package))

@pytest.fixture
def requires_numpy_2():
    """Skip test if numpy < 2.0."""
    if get_version("numpy") < Version("2.0.0"):
        pytest.skip("Requires numpy >= 2.0")

def test_numpy_2_features(requires_numpy_2):
    """Test features only available in numpy 2.x."""
    import numpy as np
    # This test only runs with numpy 2.x+
    assert hasattr(np, "some_new_api")
```

---

## Implementation Checklist

### Phase 1: Audit (Per Repository)
- [ ] Identify all tests with hardcoded version assertions
- [ ] Catalog tests that import `importlib.metadata.version`
- [ ] Check for version comparisons: `==`, `>=`, `<`, etc.
- [ ] Document current lock file generation process
- [ ] Identify Dependabot configuration state

**Search Patterns:**
```bash
# Find hardcoded version assertions
rg --type py 'version.*==.*\d+\.\d+' tests/
rg --type py 'expected.*version' tests/
rg --type py 'assert.*\d+,\s*\d+\)' tests/

# Find version checks
rg --type py 'importlib\.metadata\.version' tests/
rg --type py '__version__' tests/
rg --type py 'pkg_resources' tests/
```

### Phase 2: Refactor (Per Repository)
- [ ] Create `tests/conftest.py` with version utility helpers
- [ ] Refactor tests to use dynamic version extraction
- [ ] Replace hardcoded assertions with behavior tests
- [ ] Add version range compliance test
- [ ] Set up lock file automation (CI check + Dependabot workflow)

### Phase 3: Enable Dependabot (Per Repository)
- [ ] Create `.github/dependabot.yml` if missing
- [ ] Enable pip/poetry/uv ecosystem monitoring
- [ ] Configure auto-merge for minor/patch updates (optional)
- [ ] Set up Dependabot auto-lock workflow

**Example Dependabot Config:**
```yaml
# .github/dependabot.yml
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
    labels:
      - "dependencies"
      - "automated"
```

### Phase 4: Monitor & Iterate
- [ ] Track Dependabot PR success rate
- [ ] Identify recurring test failures
- [ ] Refine version testing patterns
- [ ] Share learnings across repos

---

## Repository Rollout Plan

### Priority Order

**Tier 1: High-Impact Repos** (Fix Immediately)
1. **Trend_Model_Project** ⚠️ Currently broken
   - **Immediate Action**: Fix PR #4214 lock file sync
   - Refactor `test_llm_dependency_compatibility.py`
   - Add lock file automation

2. **Manager-Database**
   - Check for similar patterns
   - Enable Dependabot if not active

**Tier 2: Active Development Repos**
3. **Travel-Plan-Permission** ✅ (This repo)
   - Already has good patterns (no hardcoded versions found)
   - Add lock file automation as reference implementation
   - Document as best practice example

4. **trip-planner**
   - Audit for version test patterns
   - Implement refactoring if needed

**Tier 3: Utility/Template Repos**
5. **Workflows** (shared workflows repo)
   - Create reusable workflow for lock file automation
   - Add to workflow library for all repos

6. **Template**
   - Implement best practices as default for new projects
   - Include in project scaffolding

7. **Portable-Alpha-Extension-Model**
8. **Workflows-Integration-Tests**

---

## Success Criteria

### Per Repository
- ✅ No hardcoded dependency version assertions in tests
- ✅ Lock files automatically regenerated when `pyproject.toml` changes
- ✅ Dependabot PRs pass CI without manual intervention
- ✅ Tests focus on behavior and compatibility, not specific versions

### Cross-Repository
- ✅ Shared testing utilities in common location (e.g., `Workflows` repo)
- ✅ Consistent patterns across all consumer repos
- ✅ Documentation and examples for future projects
- ✅ <5% manual intervention rate for Dependabot PRs

---

## Immediate Next Steps

### 1. Fix Trend_Model_Project PR #4214 (URGENT)
```bash
# On PR branch
uv pip compile pyproject.toml --output-file requirements.lock
git add requirements.lock
git commit -m "chore: sync lock file with numpy 2.4.0 update"
git push
```

### 2. Refactor Problematic Test (URGENT)
File: `tests/test_llm_dependency_compatibility.py`

Replace:
```python
expected_ranges = {
    "langchain": (1, 2),
    "langchain-core": (1, 2),
    "langchain-community": (0, 4),
}
```

With:
```python
def get_expected_range(package: str) -> SpecifierSet:
    """Extract declared version range from pyproject.toml."""
    with open("pyproject.toml", "rb") as f:
        pyproject = tomllib.load(f)
    for dep in pyproject["project"]["dependencies"]:
        if dep.startswith(package):
            # Parse "langchain>=1.2,<1.3" -> SpecifierSet
            ...
```

### 3. Add Lock File Automation (HIGH)
Create workflow: `.github/workflows/dependabot-auto-lock.yml`

### 4. Create Audit Report (MEDIUM)
Run audit Phase 1 across all consumer repos and document findings

---

## Questions for Discussion

1. **Lock File Tool**: Should we standardize on `uv`, `pip-tools`, or `poetry`?
   - Current: Mixed (some repos use `uv`, some use `pip-tools`)
   - Recommendation: Standardize on `uv` (faster, better dependency resolution)

2. **Auto-Merge Strategy**: Should we auto-merge passing Dependabot PRs?
   - Option A: Auto-merge minor/patch updates after CI passes
   - Option B: Require manual review for all updates
   - Option C: Auto-merge with post-merge monitoring

3. **Shared Test Utilities**: Where should common test helpers live?
   - Option A: In `Workflows` repo as importable package
   - Option B: Copy-paste pattern across repos (simpler, more duplication)
   - Option C: Separate `pytest-plugin` package

4. **Breaking Change Policy**: How should we handle major version updates?
   - Keep separate `test_compatibility_vX.py` files?
   - Use pytest marks to skip incompatible tests?
   - Maintain separate branches for major versions?

5. **Coverage Requirements**: Should version compatibility tests count toward coverage?
   - These tests don't test business logic
   - But they prevent integration issues
   - Could create separate coverage target?

---

## References

### Tools
- [packaging](https://packaging.pypa.io/): Parse and compare versions
- [uv](https://github.com/astral-sh/uv): Fast Python package installer
- [pip-tools](https://github.com/jazzband/pip-tools): Requirements compilation
- [Dependabot](https://docs.github.com/en/code-security/dependabot): Automated dependency updates

### Best Practices
- [Semantic Versioning](https://semver.org/)
- [PEP 440 – Version Identification](https://peps.python.org/pep-0440/)
- [Testing Pyramid](https://martinfowler.com/articles/practical-test-pyramid.html)

### Example Implementations
- This repo (`Travel-Plan-Permission`): Good baseline (no hardcoded versions)
- [pytest-versions](https://github.com/pytest-dev/pytest-versions): Plugin for multi-version testing
