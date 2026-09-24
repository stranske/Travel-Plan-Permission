"""Shared safeguards for CSV fields consumed by spreadsheet applications."""

from __future__ import annotations


def csv_literal_text(value: str) -> str:
    """Prefix ambiguous text so spreadsheet CSV importers preserve it literally.

    Preserve the original bytes after the prefix, including leading whitespace.
    This is an export/import convention, not a universal spreadsheet-engine escape.
    """
    if value and (
        value[0] in "=+-@＝＋－＠"
        or value[0].isspace()
        or ord(value[0]) < 32
        or ord(value[0]) == 127
    ):
        return "'" + value
    return value
