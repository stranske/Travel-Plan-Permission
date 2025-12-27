import base64
import csv
import hashlib
import os
import pathlib
import tarfile
import tempfile
import tomllib
import zipfile


def _project_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2]


def _load_project_config() -> dict:
    pyproject_path = _project_root() / "pyproject.toml"
    with pyproject_path.open("rb") as handle:
        data = tomllib.load(handle)
    return data["project"]


def _normalize_name(name: str) -> str:
    return "".join("_" if ch in "-." else ch for ch in name).lower()


def _build_metadata(project: dict) -> str:
    lines = [
        "Metadata-Version: 2.1",
        f"Name: {project['name']}",
        f"Version: {project['version']}",
        f"Summary: {project.get('description', '')}",
    ]

    authors = project.get("authors", [])
    if authors:
        author_names = ", ".join(author.get("name", "") for author in authors if author.get("name"))
        if author_names:
            lines.append(f"Author: {author_names}")

    license_info = project.get("license", {})
    if isinstance(license_info, dict):
        license_text = license_info.get("text")
        if license_text:
            lines.append(f"License: {license_text}")

    requires_python = project.get("requires-python")
    if requires_python:
        lines.append(f"Requires-Python: {requires_python}")

    keywords = project.get("keywords", [])
    if keywords:
        lines.append(f"Keywords: {', '.join(keywords)}")

    classifiers = project.get("classifiers", [])
    for classifier in classifiers:
        lines.append(f"Classifier: {classifier}")

    for requirement in project.get("dependencies", []):
        lines.append(f"Requires-Dist: {requirement}")

    optional_deps = project.get("optional-dependencies", {})
    for extra, requirements in optional_deps.items():
        lines.append(f"Provides-Extra: {extra}")
        for requirement in requirements:
            lines.append(f"Requires-Dist: {requirement}; extra == \"{extra}\"")

    readme_path = project.get("readme")
    readme_content = ""
    if readme_path:
        candidate = _project_root() / readme_path
        if candidate.exists():
            readme_content = candidate.read_text(encoding="utf-8")
            if readme_content:
                lines.append("Description-Content-Type: text/markdown")

    lines.append("")
    if readme_content:
        lines.append(readme_content)

    return "\n".join(lines)


def _write_dist_info(dist_info_path: pathlib.Path, project: dict) -> None:
    dist_info_path.mkdir(parents=True, exist_ok=True)
    metadata = _build_metadata(project)
    (dist_info_path / "METADATA").write_text(metadata, encoding="utf-8")
    wheel_metadata = "\n".join(
        [
            "Wheel-Version: 1.0",
            "Generator: tp_build_backend",
            "Root-Is-Purelib: true",
            "Tag: py3-none-any",
        ]
    )
    (dist_info_path / "WHEEL").write_text(wheel_metadata, encoding="utf-8")

    scripts = project.get("scripts", {})
    if scripts:
        lines = ["[console_scripts]"]
        for name, target in scripts.items():
            lines.append(f"{name} = {target}")
        (dist_info_path / "entry_points.txt").write_text("\n".join(lines), encoding="utf-8")


def _record_files(root: pathlib.Path, dist_info_path: pathlib.Path) -> None:
    record_rows = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        rel_path = path.relative_to(root).as_posix()
        if rel_path == f"{dist_info_path.name}/RECORD":
            continue
        digest = hashlib.sha256(path.read_bytes()).digest()
        encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        record_rows.append((rel_path, f"sha256={encoded}", str(path.stat().st_size)))

    record_rows.append((f"{dist_info_path.name}/RECORD", "", ""))

    record_path = dist_info_path / "RECORD"
    with record_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerows(record_rows)


def _copy_package_tree(target_root: pathlib.Path) -> None:
    src_root = _project_root() / "src" / "travel_plan_permission"
    target = target_root / "travel_plan_permission"
    if target.exists():
        return
    os.makedirs(target_root, exist_ok=True)
    for path in src_root.rglob("*"):
        rel_path = path.relative_to(src_root)
        destination = target / rel_path
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())


def _write_editable_pth(target_root: pathlib.Path) -> None:
    src_path = _project_root() / "src"
    pth_name = f"{_normalize_name(_load_project_config()['name'])}.pth"
    (target_root / pth_name).write_text(str(src_path), encoding="utf-8")


def _build_wheel(wheel_directory: str, editable: bool) -> str:
    project = _load_project_config()
    dist_name = _normalize_name(project["name"])
    version = project["version"]

    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)

        if editable:
            _write_editable_pth(root)
        else:
            _copy_package_tree(root)

        dist_info = root / f"{dist_name}-{version}.dist-info"
        _write_dist_info(dist_info, project)
        _record_files(root, dist_info)

        wheel_name = f"{dist_name}-{version}-py3-none-any.whl"
        wheel_path = pathlib.Path(wheel_directory) / wheel_name
        with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in root.rglob("*"):
                if file_path.is_dir():
                    continue
                archive.write(file_path, file_path.relative_to(root).as_posix())

    return wheel_name


def build_wheel(wheel_directory: str, _config_settings=None, _metadata_directory=None) -> str:
    return _build_wheel(wheel_directory, editable=False)


def build_editable(wheel_directory: str, _config_settings=None, _metadata_directory=None) -> str:
    return _build_wheel(wheel_directory, editable=True)


def get_requires_for_build_wheel(_config_settings=None) -> list[str]:
    return []


def get_requires_for_build_editable(_config_settings=None) -> list[str]:
    return []


def get_requires_for_build_sdist(_config_settings=None) -> list[str]:
    return []


def build_sdist(sdist_directory: str, _config_settings=None) -> str:
    project = _load_project_config()
    dist_name = _normalize_name(project["name"])
    version = project["version"]
    sdist_name = f"{dist_name}-{version}.tar.gz"
    root_dir = f"{dist_name}-{version}"
    sdist_path = pathlib.Path(sdist_directory) / sdist_name

    project_root = _project_root()
    with tarfile.open(sdist_path, "w:gz") as tar:
        for rel_path in ["pyproject.toml", "README.md", "setup.cfg", "setup.py"]:
            candidate = project_root / rel_path
            if candidate.exists():
                tar.add(candidate, arcname=f"{root_dir}/{rel_path}")
        backend_root = project_root / "tools" / "build_backend"
        if backend_root.exists():
            for path in backend_root.rglob("*"):
                if path.is_dir() or "__pycache__" in path.parts:
                    continue
                tar.add(path, arcname=f"{root_dir}/tools/build_backend/{path.relative_to(backend_root)}")
        src_root = project_root / "src"
        for path in src_root.rglob("*"):
            tar.add(path, arcname=f"{root_dir}/src/{path.relative_to(src_root)}")

    return sdist_name


def prepare_metadata_for_build_wheel(metadata_directory: str, _config_settings=None) -> str:
    project = _load_project_config()
    dist_name = _normalize_name(project["name"])
    version = project["version"]
    dist_info = pathlib.Path(metadata_directory) / f"{dist_name}-{version}.dist-info"
    _write_dist_info(dist_info, project)
    return dist_info.name


def prepare_metadata_for_build_editable(metadata_directory: str, _config_settings=None) -> str:
    return prepare_metadata_for_build_wheel(metadata_directory, _config_settings)
