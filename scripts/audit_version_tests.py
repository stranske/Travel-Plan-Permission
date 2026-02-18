#!/usr/bin/env python3
"""Audit tests for hardcoded dependency version patterns.

This script scans test files to identify potential issues with hardcoded
version assertions that will break when dependencies are updated.

Usage:
    python scripts/audit_version_tests.py                    # Scan current repo
    python scripts/audit_version_tests.py --repo path/to/repo  # Scan specific repo
    python scripts/audit_version_tests.py --fix              # Suggest fixes

Output:
    - List of files with potential hardcoded version issues
    - Specific patterns found and line numbers
    - Severity rating (HIGH, MEDIUM, LOW)
    - Suggested refactoring approaches
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Patterns that indicate hardcoded version issues
PATTERNS = {
    "hardcoded_version_assertion": {
        "regex": r'assert.*__version__\s*==\s*["\'][\d.]+["\']',
        "severity": "HIGH",
        "message": "Direct version string assertion",
        "fix": "Use assert_version_in_declared_range() instead",
    },
    "hardcoded_major_minor": {
        "regex": r"assert\s+\(.*\)\s*==\s*\(\s*\d+\s*,\s*\d+\s*\)",
        "severity": "HIGH",
        "message": "Hardcoded major.minor tuple comparison",
        "fix": "Use dynamic version extraction from pyproject.toml",
    },
    "expected_version_dict": {
        "regex": r"expected.*=\s*\{[^}]*:\s*\(\s*\d+\s*,\s*\d+\s*\)",
        "severity": "HIGH",
        "message": "Dictionary of expected version tuples",
        "fix": "Extract expected ranges from pyproject.toml at runtime",
    },
    "version_number_in_test_name": {
        "regex": r"def test_.*_v?\d+_\d+",
        "severity": "MEDIUM",
        "message": "Version number in test function name",
        "fix": "Use generic test names or pytest.mark for version-specific tests",
    },
    "version_comparison": {
        "regex": r'if.*version\s*[<>=]+\s*["\'][\d.]+["\']',
        "severity": "MEDIUM",
        "message": "Direct version string comparison",
        "fix": "Use has_feature() helper or hasattr() for feature detection",
    },
    "importlib_metadata_hardcode": {
        "regex": r'importlib\.metadata\.version.*==\s*["\'][\d.]+["\']',
        "severity": "HIGH",
        "message": "importlib.metadata with hardcoded version check",
        "fix": "Use assert_version_in_declared_range()",
    },
}


@dataclass
class Finding:
    """A single finding from the audit."""

    file_path: Path
    line_number: int
    line_content: str
    pattern_name: str
    severity: str
    message: str
    fix: str


def scan_file(file_path: Path) -> list[Finding]:
    """Scan a single file for hardcoded version patterns."""
    findings = []

    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.split("\n")

        for line_num, line in enumerate(lines, start=1):
            for pattern_name, pattern_info in PATTERNS.items():
                if re.search(pattern_info["regex"], line, re.IGNORECASE):
                    findings.append(
                        Finding(
                            file_path=file_path,
                            line_number=line_num,
                            line_content=line.strip(),
                            pattern_name=pattern_name,
                            severity=pattern_info["severity"],
                            message=pattern_info["message"],
                            fix=pattern_info["fix"],
                        )
                    )

    except Exception as e:
        print(f"⚠️  Error scanning {file_path}: {e}", file=sys.stderr)

    return findings


def scan_directory(root_path: Path) -> list[Finding]:
    """Scan all test files in a directory."""
    all_findings = []

    # Find test directories
    test_dirs = []
    for candidate in ["tests", "test"]:
        test_dir = root_path / candidate
        if test_dir.exists():
            test_dirs.append(test_dir)

    if not test_dirs:
        print(f"⚠️  No test directory found in {root_path}")
        return []

    # Scan all Python files in test directories
    for test_dir in test_dirs:
        for test_file in test_dir.rglob("test_*.py"):
            findings = scan_file(test_file)
            all_findings.extend(findings)

    return all_findings


def print_findings(findings: list[Finding], repo_path: Path) -> None:
    """Print findings in a formatted report."""
    if not findings:
        print("✅ No hardcoded version patterns found!")
        return

    # Group by severity
    by_severity = {"HIGH": [], "MEDIUM": [], "LOW": []}
    for finding in findings:
        by_severity[finding.severity].append(finding)

    print(f"\n{'='*80}")
    print(f"Audit Report: {repo_path.name}")
    print(f"{'='*80}\n")

    total = len(findings)
    print(f"Found {total} potential issue(s):\n")

    for severity in ["HIGH", "MEDIUM", "LOW"]:
        severity_findings = by_severity[severity]
        if not severity_findings:
            continue

        print(f"\n{severity} Priority ({len(severity_findings)} issues)")
        print("-" * 80)

        for finding in severity_findings:
            rel_path = finding.file_path.relative_to(repo_path)
            print(f"\n📍 {rel_path}:{finding.line_number}")
            print(f"   Pattern: {finding.message}")
            print(f"   Code: {finding.line_content[:80]}")
            print(f"   Fix: {finding.fix}")

    print(f"\n{'='*80}")
    print(
        f"Summary: {len(by_severity['HIGH'])} HIGH, "
        f"{len(by_severity['MEDIUM'])} MEDIUM, "
        f"{len(by_severity['LOW'])} LOW"
    )
    print(f"{'='*80}\n")


def generate_fix_suggestions(findings: list[Finding], repo_path: Path) -> None:
    """Generate detailed fix suggestions."""
    if not findings:
        return

    print("\n" + "=" * 80)
    print("Fix Suggestions")
    print("=" * 80 + "\n")

    # Group by file
    by_file = {}
    for finding in findings:
        if finding.file_path not in by_file:
            by_file[finding.file_path] = []
        by_file[finding.file_path].append(finding)

    for file_path, file_findings in by_file.items():
        rel_path = file_path.relative_to(repo_path)
        print(f"\n📝 {rel_path}")
        print("-" * 80)

        print("\nCurrent issues:")
        for finding in file_findings:
            print(f"  Line {finding.line_number}: {finding.message}")

        print("\nRecommended approach:")
        print("  1. Import version utilities:")
        print(
            "     from tests.helpers.version_utils import assert_version_in_declared_range"
        )
        print("\n  2. Replace hardcoded assertions with dynamic checks:")
        print("     # Before:")
        print("     assert version == (2, 3)")
        print("\n     # After:")
        print("     assert_version_in_declared_range('numpy')")
        print("\n  3. For feature testing, use has_feature() or hasattr():")
        print("     # Before:")
        print("     if version >= (2, 0):")
        print("         assert hasattr(obj, 'feature')")
        print("\n     # After:")
        print("     if has_feature('package', '2.0.0'):")
        print("         assert hasattr(obj, 'feature')")
        print("     # Or even better:")
        print("     if hasattr(obj, 'feature'):  # Direct feature detection")
        print("         # Test the feature")

    print("\n" + "=" * 80)
    print("Next Steps:")
    print("=" * 80)
    print("1. Review the test_dependency_version_patterns.py reference file")
    print("2. Copy version_utils.py helper to your repo")
    print("3. Refactor tests following the patterns above")
    print("4. Add lock file automation (dependabot-auto-lock.yml)")
    print("5. Run tests to verify changes")
    print("\nSee docs/DEPENDENCY_VERSION_TEST_STRATEGY.md for full details.\n")


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Audit test files for hardcoded dependency versions"
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Path to repository to scan (default: current directory)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Show detailed fix suggestions",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )

    args = parser.parse_args(argv)

    repo_path = args.repo.resolve()
    if not repo_path.exists():
        print(f"❌ Repository path does not exist: {repo_path}")
        return 1

    print(f"🔍 Scanning {repo_path}...")
    findings = scan_directory(repo_path)

    if args.json:
        import json

        json_output = [
            {
                "file": str(f.file_path.relative_to(repo_path)),
                "line": f.line_number,
                "severity": f.severity,
                "message": f.message,
                "pattern": f.pattern_name,
            }
            for f in findings
        ]
        print(json.dumps(json_output, indent=2))
        return 0

    print_findings(findings, repo_path)

    if args.fix and findings:
        generate_fix_suggestions(findings, repo_path)

    # Exit with error code if high priority issues found
    high_priority = [f for f in findings if f.severity == "HIGH"]
    return 1 if high_priority else 0


if __name__ == "__main__":
    sys.exit(main())
