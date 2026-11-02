import re
from itertools import takewhile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from travel_plan_permission.http_service import PlannerProposalStore, create_app

CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "PRODUCT_CONTRACT.md"


def _leading_whitespace(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _assert_table_line_not_indented_code_block(line: str) -> None:
    if not line.lstrip().startswith("|"):
        return
    leading = _leading_whitespace(line)
    assert "\t" not in leading and len(leading) < 4, (
        "Core functions table lines must not be indented as a Markdown code block"
    )


def _assert_product_contract(text: str) -> None:
    # A blank line ends the Markdown table, so detached rows must not count.
    table = text.split("## Core functions\n", 1)[1]
    table_lines = list(takewhile(lambda line: bool(line.strip()), table.splitlines()))
    assert len(table_lines) >= 2, "Core functions must have a table header and delimiter"
    for line in table_lines:
        _assert_table_line_not_indented_code_block(line)
    header = [cell.strip() for cell in table_lines[0].strip().strip("|").split("|")]
    delimiter = [cell.strip() for cell in table_lines[1].strip().strip("|").split("|")]
    assert len(header) == len(delimiter) == 5, "Core functions table needs five columns"
    assert header[0] == "id", "Core functions table must start with the id column"
    assert all(
        re.fullmatch(r":?-+:?", cell) for cell in delimiter
    ), "Core functions table delimiter must contain hyphens and optional colons"
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in table_lines
        if line.lstrip().startswith("| PP")
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
    "path",
    [
        pytest.param("/portal/admin", id="PP4"),
        pytest.param("/api/planner/policy-snapshot", id="PP8"),
    ],
)
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_product_contract_read_routes_reject_mutating_requests(path: str, method: str) -> None:
    client = TestClient(create_app(PlannerProposalStore()))

    response = client.request(method, path)

    assert response.status_code == 405
    assert response.headers["Allow"] == "GET"


@pytest.mark.parametrize(
    "separator",
    [
        pytest.param(None, id="missing-pp8"),
        pytest.param("\n", id="blank-line-before-pp8"),
        pytest.param(" \n", id="space-only-line-before-pp8"),
        pytest.param("\t\n", id="tab-only-line-before-pp8"),
    ],
)
def test_product_contract_rejects_missing_or_detached_pp8(
    separator: str | None,
) -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    pp8 = next(
        line for line in text.splitlines(keepends=True) if line.lstrip().startswith("| PP8 |")
    )
    broken = text.replace(pp8, "" if separator is None else separator + pp8, 1)

    with pytest.raises(AssertionError, match="Core functions must list PP1 through PP8"):
        _assert_product_contract(broken)


@pytest.mark.parametrize(
    "delimiter", ["", "| broken |", "| - | - | - | - |", "| - | - | x | - | - |"]
)
def test_product_contract_rejects_invalid_table_delimiter(delimiter: str) -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    original = next(line for line in text.splitlines() if line.startswith("|---"))
    with pytest.raises(AssertionError):
        _assert_product_contract(text.replace(original, delimiter, 1))


def test_product_contract_accepts_short_aligned_table_delimiter() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    original = next(line for line in text.splitlines() if line.startswith("|---"))
    _assert_product_contract(text.replace(original, "| - | :- | -: | :-: | - |", 1))


@pytest.mark.parametrize("padding", [" ", "  "])
def test_product_contract_accepts_whitespace_around_table_lines(padding: str) -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    padded = "\n".join(
        padding + line + padding if line.startswith("|") else line
        for line in text.splitlines()
    )
    _assert_product_contract(padded)


@pytest.mark.parametrize("padding", ["\t", "    ", "  \t"])
def test_product_contract_rejects_codeblock_indented_table_lines(padding: str) -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    padded = "\n".join(
        padding + line if line.startswith("|") else line for line in text.splitlines()
    )
    with pytest.raises(AssertionError, match="code block"):
        _assert_product_contract(padded)
