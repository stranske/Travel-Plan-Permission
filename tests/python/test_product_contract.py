from itertools import takewhile
from pathlib import Path

import pytest

CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "PRODUCT_CONTRACT.md"


def _assert_product_contract(text: str) -> None:
    # A blank line ends the Markdown table, so detached rows must not count.
    table = text.split("## Core functions\n", 1)[1]
    table_lines = takewhile(lambda line: bool(line.strip()), table.splitlines())
    rows = [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in table_lines
        if line.startswith("| PP")
    ]
    assert [cells[0] for cells in rows] == [
        f"PP{number}" for number in range(1, 9)
    ], "Core functions must list PP1 through PP8 exactly once, in order"
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


def test_product_contract_lists_pp1_through_pp8_with_current_statuses() -> None:
    _assert_product_contract(CONTRACT.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "separator",
    [
        pytest.param(None, id="missing-pp8"),
        pytest.param("\n", id="blank-line-before-pp8"),
        pytest.param(" \n", id="space-only-line-before-pp8"),
        pytest.param("\t\n", id="tab-only-line-before-pp8"),
    ],
)
def test_product_contract_rejects_missing_or_detached_pp8(separator: str | None) -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    pp8 = next(line for line in text.splitlines(keepends=True) if line.startswith("| PP8 |"))
    broken = text.replace(pp8, "" if separator is None else separator + pp8, 1)

    with pytest.raises(AssertionError, match="Core functions must list PP1 through PP8"):
        _assert_product_contract(broken)
