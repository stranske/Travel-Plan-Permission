from pathlib import Path


def test_product_contract_lists_pp1_through_pp8_with_current_statuses():
    contract = Path(__file__).resolve().parents[2] / "docs" / "PRODUCT_CONTRACT.md"
    rows = {
        cells[0]: cells
        for line in contract.read_text().splitlines()
        if line.startswith("| PP")
        for cells in [[cell.strip() for cell in line.strip("|").split("|")]]
    }
    assert set(rows) == {f"PP{number}" for number in range(1, 9)}
    assert rows["PP4"][-1] == "WORKS"
    assert rows["PP8"][-1] == "WORKS"
    assert "GET /api/planner/policy-snapshot" in rows["PP8"][2]
