"""Reading an expense receipt — where a misparse becomes a wrong reimbursement.

`ReceiptProcessor` turns OCR'd text into the amount, date and vendor on an expense claim. Nothing
here raises: a misread total is simply claimed, and the number looks exactly as ordinary as a
right one.

THIS FILE SHIPS A FIX. `TOTAL_PATTERN` captured `[0-9]+(?:[.,][0-9]{2})?`, which against
"TOTAL: 1,234.56" matched "1" then ",23" — yielding "1,23" and, after stripping the comma, 123.
Every four-figure total was claimed at roughly a tenth of its value, and the receipt was WORSE off
for carrying the word "Total": the no-keyword fallback already parsed thousands separators
correctly, so the same number read correctly without the label and wrongly with it.
"""

from __future__ import annotations

from datetime import date

import pytest

from travel_plan_permission.receipts import ReceiptProcessor

# ---------------------------------------------------------------------------------------------
# Totals.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("TOTAL: 1,234.56", "1234.56"),
        ("Total 12,000.00", "12000.00"),
        ("Amount due 2,500.00", "2500.00"),
        ("Grand total 1,000.00", "1000.00"),
    ],
)
def test_a_thousands_separator_survives_the_total_line(text, expected):
    """THE REGRESSION THIS FIXES.

    Before, "1,234.56" was captured as "1,23" and became 123 — a tenth of the claim. It was
    systematic: every total above 999 with a separator was affected.
    """
    assert str(ReceiptProcessor._parse_total(text)) == expected


def test_the_keyword_path_agrees_with_the_bare_fallback():
    """The property that makes the bug obvious once stated.

    A number should not parse differently because the word "Total" sits in front of it. The
    fallback always handled separators; the keyword pattern did not, so the label made the answer
    worse.
    """
    assert ReceiptProcessor._parse_total("Total 1,234.56") == ReceiptProcessor._parse_total(
        "1,234.56"
    )


def test_the_labelled_total_beats_larger_unlabelled_numbers():
    """A receipt carries an invoice number, a card number and a phone number. The label is what
    distinguishes the amount from the rest, so it must win even when something bigger is present.
    """
    text = "Invoice 998877\nSubtotal 10.00\nTax 2.00\nTotal 12.00"
    assert str(ReceiptProcessor._parse_total(text)) == "12.00"


def test_the_largest_labelled_total_wins():
    """Receipts restate the total (summary, then payment line). Taking the largest is how the
    grand total beats a partial one."""
    assert str(ReceiptProcessor._parse_total("Total 12.00\nTotal 15.00")) == "15.00"


def test_without_a_label_the_largest_money_shaped_amount_is_used():
    """A fallback, and a deliberately crude one — better than claiming nothing from a receipt
    whose OCR lost the word "Total"."""
    assert str(ReceiptProcessor._parse_total("5.00\n99.99\n12.50")) == "99.99"


def test_a_receipt_with_no_numbers_yields_none():
    """None, not zero. A zero claim reads as a free purchase rather than an unreadable receipt."""
    assert ReceiptProcessor._parse_total("thank you for your custom") is None


def test_a_whole_number_total_is_read():
    assert str(ReceiptProcessor._parse_total("Total 12")) == "12"


# ---------------------------------------------------------------------------------------------
# Dates. The ordering of the format list is a policy, not an accident.
# ---------------------------------------------------------------------------------------------


def test_an_iso_date_is_read():
    assert ReceiptProcessor._parse_date("2026-08-30") == date(2026, 8, 30)


def test_a_slashed_date_is_read_as_month_first():
    """DOCUMENTED AMBIGUITY. "03/04/2026" is March 4 under the US reading and April 3 under the
    European one, and nothing in the text says which.

    WHAT DECIDES IT IS THE SEPARATOR, NOT THE LIST ORDER — established by break demo, because I
    first wrote this docstring blaming the ordering. The list holds `%m/%d/%Y` and `%d-%m-%Y` and
    no slashed day-first form at all, so a slash can only ever parse month-first and a dash only
    day-first. Reordering the list changes nothing, and a break that reorders it correctly catches
    nothing. Adding `%d/%m/%Y` is what would make order load-bearing, and that would be the change
    to review carefully."""
    assert ReceiptProcessor._parse_date("03/04/2026") == date(2026, 3, 4)


def test_a_dashed_date_is_read_as_day_first():
    """And the opposite convention for dashes — the pairing most likely to surprise, since the
    same digits in the same order mean different days depending on which separator the printer
    used. That asymmetry is a property of which formats are LISTED, not of their order."""
    assert ReceiptProcessor._parse_date("03-04-2026") == date(2026, 4, 3)


def test_a_two_digit_year_is_accepted():
    assert ReceiptProcessor._parse_date("03/04/26") == date(2026, 3, 4)


@pytest.mark.parametrize("text", ["no date here", "", "99/99/9999"])
def test_an_unreadable_date_is_none(text):
    """A guessed date on an expense claim lands the cost in the wrong period."""
    assert ReceiptProcessor._parse_date(text) is None


# ---------------------------------------------------------------------------------------------
# Vendor.
# ---------------------------------------------------------------------------------------------


def test_the_first_line_is_the_vendor():
    assert ReceiptProcessor._parse_vendor("Acme Hotel\n123 Station Road") == "Acme Hotel"


def test_a_receipt_header_is_skipped():
    """Many printers put the word "Receipt" on line one. Taking it literally files every expense
    against a vendor called Receipt."""
    assert ReceiptProcessor._parse_vendor("Receipt\nAcme Hotel") == "Acme Hotel"


def test_a_header_with_nothing_after_it_is_none():
    assert ReceiptProcessor._parse_vendor("Receipt") is None


@pytest.mark.parametrize("text", ["", "   \n   \n"])
def test_blank_text_has_no_vendor(text):
    assert ReceiptProcessor._parse_vendor(text) is None


def test_leading_whitespace_is_stripped():
    assert ReceiptProcessor._parse_vendor("   Acme Hotel   \nrest") == "Acme Hotel"
