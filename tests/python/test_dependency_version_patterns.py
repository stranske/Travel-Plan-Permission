"""Reference implementation: Version-agnostic dependency testing.

This test file demonstrates best practices for testing dependency compatibility
without hardcoding version numbers. Use these patterns as templates for other repos.

Key Principles:
1. Test behavior and compatibility, not specific versions
2. Derive expectations from pyproject.toml at runtime
3. Focus on features and APIs, not version strings
4. Skip tests gracefully when features aren't available
"""

import sys
from pathlib import Path

import pytest

# Add helpers to path for this reference implementation
sys.path.insert(0, str(Path(__file__).parent.parent / "helpers"))

from version_utils import (
    assert_all_dependencies_within_ranges,
    assert_version_in_declared_range,
    get_package_version,
    has_feature,
)


class TestDependencyVersions:
    """Comprehensive tests for dependency version compliance."""

    def test_all_dependencies_within_declared_ranges(self) -> None:
        """All installed packages should satisfy pyproject.toml constraints.

        This is the recommended "catch-all" test that prevents lock file
        drift and catches installation issues.

        ✅ Passes when all dependencies match declared ranges
        ❌ Fails when lock file is out of sync or manual installs conflict
        """
        assert_all_dependencies_within_ranges()

    @pytest.mark.parametrize(
        "package",
        [
            "numpy",
            "pandas",
            "pytest",
            "hypothesis",
            # Add other critical dependencies
        ],
    )
    def test_individual_dependency_ranges(self, package: str) -> None:
        """Each critical dependency should satisfy its declared range.

        This provides more granular failure messages than the catch-all test.
        Useful for debugging which specific package is out of range.
        """
        assert_version_in_declared_range(package)


class TestNumpyCompatibility:
    """Example: Testing NumPy compatibility without hardcoded versions.

    ✅ GOOD: Tests focus on API availability and behavior
    ❌ BAD: Tests that assert "numpy == 2.3.4"
    """

    def test_numpy_version_compatible(self) -> None:
        """NumPy version should be within declared range."""
        assert_version_in_declared_range("numpy")

    def test_numpy_core_apis_available(self) -> None:
        """Core NumPy APIs should be available in all supported versions.

        This tests that we're using NumPy correctly, regardless of version.
        If this fails, it means either:
        1. NumPy made a breaking change (need to update code)
        2. We're using deprecated APIs (need to update code)
        """
        import numpy as np

        # Core APIs that should always exist
        required_apis = [
            "ndarray",
            "array",
            "zeros",
            "ones",
            "arange",
            "linspace",
            "concatenate",
            "mean",
            "std",
            "sum",
            "dot",
        ]

        missing = [api for api in required_apis if not hasattr(np, api)]
        assert not missing, f"NumPy APIs missing: {missing}"

    def test_numpy_array_creation(self) -> None:
        """Test that NumPy array operations work as expected.

        Focus on behavior, not version numbers.
        """
        import numpy as np

        arr = np.array([1, 2, 3, 4, 5])
        assert len(arr) == 5
        assert arr.mean() == 3.0
        assert arr.std() > 0


class TestPandasCompatibility:
    """Example: Testing pandas compatibility with version-gated features."""

    def test_pandas_version_compatible(self) -> None:
        """Pandas version should be within declared range."""
        assert_version_in_declared_range("pandas")

    def test_pandas_core_functionality(self) -> None:
        """Core pandas functionality should work in all supported versions."""
        import pandas as pd

        # Test DataFrame creation and basic operations
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        assert len(df) == 3
        assert list(df.columns) == ["a", "b"]
        assert df["a"].sum() == 6

    @pytest.mark.skipif(
        not has_feature("pandas", "2.0.0"),
        reason="PyArrow dtype only available in pandas 2.0+",
    )
    def test_pandas_pyarrow_dtype(self) -> None:
        """Test PyArrow backend (pandas 2.0+ feature).

        This shows how to handle version-specific features gracefully.
        The test is skipped if pandas < 2.0, but runs if pandas >= 2.0.
        """
        import pandas as pd

        # This feature was added in pandas 2.0
        df = pd.DataFrame({"a": [1, 2, 3]}, dtype="int64[pyarrow]")
        assert "pyarrow" in str(df["a"].dtype)


class TestPytestCompatibility:
    """Example: Testing pytest compatibility."""

    def test_pytest_version_compatible(self) -> None:
        """Pytest version should be within declared range."""
        assert_version_in_declared_range("pytest")

    def test_pytest_marks_available(self) -> None:
        """Core pytest marks should be available."""
        # These should work in all supported pytest versions
        assert hasattr(pytest.mark, "parametrize")
        assert hasattr(pytest.mark, "skip")
        assert hasattr(pytest.mark, "skipif")
        assert hasattr(pytest.mark, "xfail")


class TestHypothesisCompatibility:
    """Example: Testing hypothesis compatibility."""

    def test_hypothesis_version_compatible(self) -> None:
        """Hypothesis version should be within declared range."""
        assert_version_in_declared_range("hypothesis")

    def test_hypothesis_core_strategies(self) -> None:
        """Core hypothesis strategies should be available."""
        from hypothesis import strategies as st

        # Test that core strategies exist and work
        assert hasattr(st, "integers")
        assert hasattr(st, "text")
        assert hasattr(st, "lists")

        # Generate a sample value to verify it works
        int_strategy = st.integers(min_value=1, max_value=10)
        sample = int_strategy.example()
        assert 1 <= sample <= 10


# Anti-pattern examples (DO NOT USE)


class TestAntiPatterns:
    """Examples of BAD patterns - DO NOT USE THESE!

    These tests are marked with xfail to show what NOT to do.
    """

    @pytest.mark.xfail(reason="Anti-pattern: hardcoded version check")
    def test_hardcoded_version_bad(self) -> None:
        """❌ BAD: Hardcoded version assertion.

        This test will fail every time the dependency is updated.
        Don't test specific version numbers unless absolutely necessary.
        """
        import numpy as np

        # ❌ DON'T DO THIS
        assert np.__version__ == "2.3.4"

    @pytest.mark.xfail(reason="Anti-pattern: major.minor version tuple")
    def test_hardcoded_major_minor_bad(self) -> None:
        """❌ BAD: Hardcoded major.minor version.

        This pattern fails every time minor version increments.
        """
        version = get_package_version("numpy")
        major, minor = version.major, version.minor

        # ❌ DON'T DO THIS
        assert (major, minor) == (2, 3)

    @pytest.mark.xfail(reason="Anti-pattern: version-based feature assumption")
    def test_version_based_feature_detection_bad(self) -> None:
        """❌ BAD: Assuming features based on version number.

        Instead, test for the feature directly (hasattr, try/except).
        """
        import pandas as pd

        # ❌ DON'T DO THIS
        if pd.__version__ >= "2.0.0":
            assert hasattr(pd, "some_feature")

        # ✅ DO THIS INSTEAD
        if hasattr(pd, "some_feature"):
            # Test the feature
            pass


# Recommended patterns


class TestRecommendedPatterns:
    """Examples of GOOD patterns - USE THESE!"""

    def test_feature_detection_good(self) -> None:
        """✅ GOOD: Direct feature detection.

        Test for features directly, not based on version numbers.
        """
        import pandas as pd

        # ✅ DO THIS
        if hasattr(pd, "DataFrame"):
            df = pd.DataFrame({"a": [1, 2, 3]})
            assert len(df) == 3

    def test_version_range_good(self) -> None:
        """✅ GOOD: Test that version is in declared range.

        This ensures consistency with pyproject.toml without hardcoding.
        """
        assert_version_in_declared_range("numpy")
        assert_version_in_declared_range("pandas")

    def test_behavioral_compatibility_good(self) -> None:
        """✅ GOOD: Test behavior, not version.

        If the behavior works, the version is compatible.
        """
        import numpy as np

        # Test actual functionality
        arr = np.array([1, 2, 3])
        assert arr.sum() == 6  # This should work in any numpy version

    @pytest.mark.skipif(
        not has_feature("pandas", "2.0.0"),
        reason="Feature requires pandas 2.0+",
    )
    def test_version_gated_feature_good(self) -> None:
        """✅ GOOD: Gracefully skip when feature unavailable.

        Use has_feature() helper for clean version-gated testing.
        """
        # Test only runs if pandas >= 2.0
        import pandas as pd

        # Test feature that was added in 2.0
        df = pd.DataFrame({"a": [1, 2, 3]})
        # ... test the feature ...
        assert len(df) == 3


# Additional notes:
#
# 1. When to test versions:
#    - ✅ Test that installed version is in declared range
#    - ✅ Test that required features exist
#    - ❌ Don't test specific version strings
#
# 2. When features depend on versions:
#    - Use has_feature() helper
#    - Or use hasattr() for direct feature detection
#    - Or use pytest.skipif for version-gated tests
#
# 3. If you MUST test a specific version:
#    - Ask: "Why does this specific version matter?"
#    - If it's a known breaking change, test the behavior that broke
#    - If it's a required feature, test for feature availability
#    - Only as last resort: use has_feature() or skipif
