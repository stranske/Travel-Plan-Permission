from itertools import takewhile
from pathlib import Path


def test_product_contract_lists_pp1_through_pp8_with_current_statuses() -> None:
    contract = Path(__file__).resolve().parents[2] / "docs" / "PRODUCT_CONTRACT.md"
    # A blank line ends the Markdown table, so detached rows must not count.
    table = contract.read_text(encoding="utf-8").split("## Core functions\n", 1)[1]
    table_lines = takewhile(lambda line: bool(line.strip()), table.splitlines())
    rows = [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in table_lines
        if line.startswith("| PP")
    ]
    assert [cells[0] for cells in rows] == [f"PP{number}" for number in range(1, 9)]
    assert all(len(cells) == 5 for cells in rows)
    assert {cells[0]: cells[-1] for cells in rows} == {
        "PP1": "WORKS",
        "PP2": "WORKS",
        "PP3": "WORKS",
        "PP4": "WORKS",
        "PP5": "WORKS",
        "PP6": "PARTIAL",
        "PP7": "WORKS",
        "PP8": "WORKS",
    }
    assert "`GET /portal/admin`" in rows[3][2]
    assert "`GET /api/planner/policy-snapshot`" in rows[7][2]
