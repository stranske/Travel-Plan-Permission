#!/usr/bin/env python3
"""Freeze cached lookup keys after slimming the organization workbook.

The Federal Meal Total Rates sheet derives its ZIP key in column A from a
column removed by the runtime-template slimming step. Excel would otherwise
recalculate those keys to errors and break exact-match per-diem lookups.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_FORMULA = f"{{{_MAIN_NS}}}f"
_VALUE = f"{{{_MAIN_NS}}}v"
_CELL = f"{{{_MAIN_NS}}}c"
_ZIP_CELL = re.compile(r"A\d+")


def freeze_federal_zip_keys(sheet_xml: bytes) -> tuple[bytes, int]:
    """Replace column-A formulas with their existing cached ZIP values."""

    ET.register_namespace("", _MAIN_NS)
    root = ET.fromstring(sheet_xml)
    frozen = 0
    for cell in root.iter(_CELL):
        if not _ZIP_CELL.fullmatch(cell.attrib.get("r", "")):
            continue
        formula = cell.find(_FORMULA)
        value = cell.find(_VALUE)
        if formula is None:
            continue
        if value is None or value.text is None:
            raise ValueError(f"Formula cell {cell.attrib['r']} has no cached ZIP value")
        cell.remove(formula)
        frozen += 1
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), frozen


def finalize_template(path: Path, *, check: bool = False) -> tuple[int, str]:
    """Finalize or validate the normalized runtime template."""

    member = "xl/worksheets/sheet3.xml"
    with zipfile.ZipFile(path) as source:
        updated_sheet, frozen = freeze_federal_zip_keys(source.read(member))
        if check:
            if frozen:
                raise ValueError(f"{frozen} Federal Meal Total Rates ZIP formulas remain")
            return 0, hashlib.sha256(path.read_bytes()).hexdigest()

        with tempfile.NamedTemporaryFile(
            dir=path.parent, suffix=".xlsx", delete=False
        ) as handle:
            temporary_path = Path(handle.name)
        try:
            with zipfile.ZipFile(
                temporary_path, "w", compression=zipfile.ZIP_DEFLATED
            ) as output:
                for item in source.infolist():
                    output.writestr(
                        item, updated_sheet if item.filename == member else source.read(item)
                    )
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)

    return frozen, hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("template", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    frozen, digest = finalize_template(args.template, check=args.check)
    print(f"frozen={frozen} sha256={digest}")


if __name__ == "__main__":
    main()
