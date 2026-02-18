#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from venv import EnvBuilder


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def install_and_verify(
    label: str,
    repo_root: Path,
    editable: bool,
    no_build_isolation: bool,
    no_cache: bool,
    no_deps: bool,
    system_site_packages: bool,
    skip_import_check: bool,
) -> None:
    with tempfile.TemporaryDirectory(prefix=f"tpp-{label}-") as temp_dir:
        venv_dir = Path(temp_dir) / "venv"
        EnvBuilder(with_pip=True, system_site_packages=system_site_packages).create(
            venv_dir
        )
        python = venv_python(venv_dir)

        install_cmd = [str(python), "-m", "pip", "install"]
        if no_build_isolation:
            install_cmd.append("--no-build-isolation")
        if no_cache:
            install_cmd.append("--no-cache-dir")
        if no_deps:
            install_cmd.append("--no-deps")
        if editable:
            install_cmd.append("-e")
        install_cmd.append(str(repo_root))
        run(install_cmd)

        if not skip_import_check:
            verify_cmd = [
                str(python),
                "-c",
                (
                    "from travel_plan_permission import ("
                    "check_trip_plan, "
                    "list_allowed_vendors, "
                    "reconcile, "
                    "fill_travel_spreadsheet, "
                    "TripPlan, "
                    "__version__, "
                    "); "
                    "print(__version__)"
                ),
            ]
            run(verify_cmd)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify editable and non-editable installs."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root to install from",
    )
    parser.add_argument(
        "--no-build-isolation",
        action="store_true",
        help="Pass --no-build-isolation to pip (useful in offline environments).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Pass --no-cache-dir to pip to avoid using cached wheels.",
    )
    parser.add_argument(
        "--no-deps",
        action="store_true",
        help="Pass --no-deps to pip to skip dependency installation.",
    )
    parser.add_argument(
        "--system-site-packages",
        action="store_true",
        help="Create the venv with access to system site packages.",
    )
    parser.add_argument(
        "--skip-import-check",
        action="store_true",
        help="Skip the import check after installation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.path.resolve()

    install_and_verify(
        label="editable",
        repo_root=repo_root,
        editable=True,
        no_build_isolation=args.no_build_isolation,
        no_cache=args.no_cache,
        no_deps=args.no_deps,
        system_site_packages=args.system_site_packages,
        skip_import_check=args.skip_import_check,
    )
    install_and_verify(
        label="noneditable",
        repo_root=repo_root,
        editable=False,
        no_build_isolation=args.no_build_isolation,
        no_cache=args.no_cache,
        no_deps=args.no_deps,
        system_site_packages=args.system_site_packages,
        skip_import_check=args.skip_import_check,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
