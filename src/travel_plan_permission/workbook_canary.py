"""Generate and structurally verify the organization workbook canary."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from openpyxl import load_workbook

from .canonical import CanonicalTripPlan, canonical_trip_plan_to_model
from .policy_api import fill_travel_spreadsheet

_SHEET = "Itinerary Form"
_PRESERVED_FORMULAS = {
    "H6": '=IFERROR(VLOOKUP(G6,Locations!A:F,4,FALSE)&", "'
    '&VLOOKUP(G6,Locations!A:F,6,FALSE),"City / State")',
    "O22": "=SUM(M17,C23,F23,K23)",
    "O39": "=K36*O36",
    "G103": "=SUM(G97:G102)",
}


def prepare_organization_workbook_canary(
    fixture_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Create a no-submission workbook and verify its critical contract."""

    canonical = CanonicalTripPlan.model_validate_json(
        fixture_path.read_text(encoding="utf-8")
    )
    fill_travel_spreadsheet(
        canonical_trip_plan_to_model(canonical),
        output_path,
        canonical_plan=canonical,
    )

    with ZipFile(output_path) as archive:
        corrupt_member = archive.testzip()
    if corrupt_member is not None:
        raise RuntimeError(f"Generated workbook contains a corrupt member: {corrupt_member}")

    workbook = load_workbook(output_path, read_only=True, data_only=False)
    try:
        sheet = workbook[_SHEET]
        expected_inputs = {
            "C6": canonical.traveler_name,
            "G6": int(canonical.destination_zip),
            "C7": canonical.business_purpose,
            "M7": datetime.combine(canonical.depart_date, time()),
            "M8": datetime.combine(canonical.return_date, time()),
        }
        for cell_ref, expected in expected_inputs.items():
            actual = sheet[cell_ref].value
            if actual != expected:
                raise RuntimeError(
                    f"Organization workbook cell {cell_ref} was {actual!r}; expected {expected!r}"
                )
        for cell_ref, expected in _PRESERVED_FORMULAS.items():
            actual = sheet[cell_ref].value
            if actual != expected:
                raise RuntimeError(
                    f"Organization workbook formula {cell_ref} drifted: {actual!r}"
                )
        if not workbook.calculation.fullCalcOnLoad or not workbook.calculation.forceFullCalc:
            raise RuntimeError("Organization workbook is not marked for full Excel recalculation")
    finally:
        workbook.close()

    return {
        "artifact": output_path.name,
        "artifact_bytes": output_path.stat().st_size,
        "destination_zip": canonical.destination_zip,
        "formulas_verified": sorted(_PRESERVED_FORMULAS),
        "recalculate_on_open": True,
        "submission_performed": False,
        "traveler_name": canonical.traveler_name,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    result = prepare_organization_workbook_canary(args.fixture, args.output)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
