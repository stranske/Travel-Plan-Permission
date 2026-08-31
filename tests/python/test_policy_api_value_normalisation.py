"""Value coercion in `policy_api`: what a typed cell becomes before it reaches a spreadsheet.

`_normalize_dropdown_value` was entirely unexercised. It decides whether what a user typed maps to
an allowed option — exact match first, then a prefix match, then the original value unchanged. A
defect here does not raise; it writes a DIFFERENT option into a travel plan, or silently leaves an
unmatched string where a validated one was expected.

The date and currency coercions beside it fail the same way: they return `None` for input they
cannot read, and `None` is also what a genuinely absent field returns.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from travel_plan_permission.policy_api import (
    _format_currency_value,
    _format_date_value,
    _format_datetime_value,
    _normalize_dropdown_value,
)

OPTIONS = ["Economy", "Premium Economy", "Business"]


# ---------------------------------------------------------------------------------------------
# Dropdown normalisation.
# ---------------------------------------------------------------------------------------------


def test_an_exact_match_returns_the_declared_option():
    """Returns the OPTION, not the input — so the sheet gets the canonical spelling."""
    assert _normalize_dropdown_value("Economy", OPTIONS) == "Economy"


@pytest.mark.parametrize("typed", ["economy", "ECONOMY", "  Economy  ", "eCoNoMy"])
def test_case_and_surrounding_space_do_not_defeat_an_exact_match(typed):
    """People type into a form. Matching only exact bytes would reject most real input."""
    assert _normalize_dropdown_value(typed, OPTIONS) == "Economy"


def test_an_exact_match_beats_a_prefix_match():
    """`Economy` is also a prefix of `Economy Plus`; the exact option must win.

    This is the ordering that keeps the fallback safe. If prefix matching ran first, a value that
    exactly names one option could be rewritten to a different, longer one.
    """
    options = ["Economy Plus", "Economy"]
    assert _normalize_dropdown_value("Economy", options) == "Economy"


def test_a_prefix_match_resolves_an_abbreviation():
    assert _normalize_dropdown_value("Prem", OPTIONS) == "Premium Economy"


def test_an_unmatched_value_is_returned_unchanged_not_dropped():
    """Silently emptying the cell would lose what the user meant; downstream validation is what
    rejects it, and it can only do that if the value survives to be seen."""
    assert _normalize_dropdown_value("Sleeper Car", OPTIONS) == "Sleeper Car"


@pytest.mark.parametrize(
    "value, options",
    [(42, OPTIONS), (None, OPTIONS), ("Economy", "Economy"), ("Economy", None)],
)
def test_non_string_values_and_non_list_options_pass_straight_through(value, options):
    """The guard that makes this safe to call on every cell, typed or not."""
    assert _normalize_dropdown_value(value, options) == value


def test_an_empty_option_list_leaves_the_value_alone():
    assert _normalize_dropdown_value("Economy", []) == "Economy"


# ---------------------------------------------------------------------------------------------
# Date and datetime coercion. Unreadable input must not become a plausible date.
# ---------------------------------------------------------------------------------------------


def test_an_iso_date_string_is_parsed():
    assert _format_date_value("2026-08-30") == date(2026, 8, 30)


@pytest.mark.parametrize("bad", ["30/08/2026", "not-a-date", "2026-13-45", ""])
def test_an_unparseable_date_is_none_rather_than_a_guess(bad):
    """Guessing a format is worse than refusing: a misread date books the wrong travel dates."""
    assert _format_date_value(bad) is None


def test_a_datetime_is_narrowed_to_its_date():
    assert _format_date_value(datetime(2026, 8, 30, 14, 30)) == date(2026, 8, 30)


def test_a_date_passes_through_unchanged():
    assert _format_date_value(date(2026, 8, 30)) == date(2026, 8, 30)


@pytest.mark.parametrize("value", [42, None, ["2026-08-30"], object()])
def test_a_value_of_the_wrong_shape_is_none(value):
    assert _format_date_value(value) is None
    assert _format_datetime_value(value) is None


def test_an_iso_datetime_is_parsed_and_a_bad_one_is_not():
    assert _format_datetime_value("2026-08-30T14:30:00") == datetime(2026, 8, 30, 14, 30)
    assert _format_datetime_value("half past two") is None


# ---------------------------------------------------------------------------------------------
# Currency. Money quantised to cents, or refused.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("1234.567", Decimal("1234.57")),
        (1234.5, Decimal("1234.50")),
        (1234, Decimal("1234.00")),
    ],
)
def test_currency_is_quantised_to_cents(value, expected):
    """A trailing third decimal in a cost column is a rounding disagreement waiting to happen."""
    assert _format_currency_value(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        (Decimal("0.005"), Decimal("0.00")),
        (Decimal("0.015"), Decimal("0.02")),
        (Decimal("0.025"), Decimal("0.02")),
    ],
)
def test_a_half_cent_rounds_to_even_not_away_from_zero(value, expected):
    """BANKER'S ROUNDING, pinned because it surprises people rather than because it is wrong.

    `Decimal.quantize` defaults to ROUND_HALF_EVEN, so 0.005 becomes 0.00 and 0.015 becomes 0.02.
    I expected 0.01 for the first and had to correct the test, not the code. Writing the three
    cases out makes the convention explicit: anyone who later "fixes" this to round half up will
    change every half-cent in the fleet's cost columns, and will be told so by a failing test
    rather than by a finance disagreement months later.
    """
    assert _format_currency_value(value) == expected


@pytest.mark.parametrize("bad", ["not money", "", "£100", None, ["100"]])
def test_unreadable_currency_is_none(bad):
    assert _format_currency_value(bad) is None
