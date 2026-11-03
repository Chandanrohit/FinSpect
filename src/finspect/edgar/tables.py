"""Small shared helpers for the span-heavy tables in SEC HTML filings."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from bs4 import Tag


def expand_table_grid(table: Tag) -> list[list[str]]:
    """Expand HTML row and column spans while excluding nested-table rows."""
    rows: list[list[str]] = []
    pending: dict[int, tuple[str, int]] = {}
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        row: dict[int, str] = {}
        next_pending: dict[int, tuple[str, int]] = {}
        for column, (value, remaining) in pending.items():
            row[column] = value
            if remaining > 1:
                next_pending[column] = (value, remaining - 1)
        column = 0
        cells = [cell for cell in tr.find_all(["th", "td"]) if cell.find_parent("table") is table]
        for cell in cells:
            while column in row:
                column += 1
            value = re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).replace("\xa0", " ").strip()
            try:
                colspan = max(1, min(30, int(cell.get("colspan", 1))))
                rowspan = max(1, min(30, int(cell.get("rowspan", 1))))
            except (TypeError, ValueError):
                colspan = rowspan = 1
            for offset in range(colspan):
                index = column + offset
                row[index] = value
                if rowspan > 1:
                    next_pending[index] = (value, rowspan - 1)
            column += colspan
        pending = next_pending
        if row:
            rows.append([row.get(i, "") for i in range(max(row) + 1)])
    width = max((len(row) for row in rows), default=0)
    return [row + [""] * (width - len(row)) for row in rows]


def parse_sec_amount(value: str) -> Decimal | None:
    """Parse a numeric cell, including SEC accounting parentheses and dashes."""
    text = value.strip().replace("−", "-").replace("$", "").replace(",", "")
    if text in {"—", "–", "-"}:
        return Decimal(0)
    if not re.fullmatch(r"\(?\s*-?\s*\d+(?:\.\d+)?\s*\)?", text):
        return None
    negative = text.startswith("(") or text.endswith(")")
    try:
        amount = Decimal(text.strip().strip("()").replace(" ", ""))
    except InvalidOperation:
        return None
    return -abs(amount) if negative else amount
