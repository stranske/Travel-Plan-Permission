from pathlib import Path

from travel_plan_permission.workbook_canary import (
    main,
    prepare_organization_workbook_canary,
)


def _fixture() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "washington_dc_business_trip.json"


def test_prepare_organization_workbook_canary(tmp_path: Path) -> None:
    output = tmp_path / "business-trip.xlsx"

    result = prepare_organization_workbook_canary(_fixture(), output)

    assert output.is_file()
    assert result["traveler_name"] == "Taylor Morgan"
    assert result["destination_zip"] == "20001"
    assert result["recalculate_on_open"] is True
    assert result["submission_performed"] is False
    assert result["formulas_verified"] == ["G103", "H6", "O22", "O39"]


def test_workbook_canary_cli_reports_json(tmp_path: Path, capsys) -> None:
    output = tmp_path / "business-trip.xlsx"

    assert main(["--fixture", str(_fixture()), "--output", str(output)]) == 0

    assert '"submission_performed": false' in capsys.readouterr().out
