from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from bs4 import BeautifulSoup, Tag


class EquityStatementError(ValueError):
    """Raised when a filing does not yield one unambiguous equity statement."""


@dataclass(frozen=True, slots=True)
class EquityStatement:
    fiscal_year: int
    period_end: str
    unit: str
    ending_equity: Decimal
    components: dict[str, Decimal]
    table_index: int


YEAR_RE = re.compile(r"(?<!\d)(?:19|20|21)\d{2}(?!\d)")
AMOUNT_RE = re.compile(
    r"^\s*(?:\$\s*)?(?P<amount>\(?\s*-?\s*[\d,]+(?:\.\d+)?\s*\)?|[—–-])\s*$"
)
BALANCE_ROW_RE = re.compile(
    r"\b(?:balance|balances|ending balances|beginning balances)\b", re.I
)
TOTAL_EQUITY_RE = re.compile(
    r"\btotal\s+(?:shareholders?['’]?|stockholders?['’]?)\s+equity\b", re.I
)


def _text(node: Tag) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True).replace("\xa0", " ")).strip()


def _expand_table(table: Tag) -> list[list[str]]:
    """Expand HTML colspan/rowspan so fiscal-year columns remain aligned."""
    pending: dict[int, tuple[str, int]] = {}
    output: list[list[str]] = []
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
        cells = [
            cell for cell in tr.find_all(["th", "td"])
            if cell.find_parent("table") is table
        ]
        for cell in cells:
            while column in row:
                column += 1
            value = _text(cell)
            try:
                colspan = max(1, min(50, int(cell.get("colspan", 1))))
                rowspan = max(1, min(50, int(cell.get("rowspan", 1))))
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
            output.append([row.get(index, "") for index in range(max(row) + 1)])
    width = max((len(row) for row in output), default=0)
    return [row + [""] * (width - len(row)) for row in output]


def _amount(value: str) -> Decimal | None:
    match = AMOUNT_RE.fullmatch(value.replace("−", "-").strip())
    if not match:
        return None
    raw = match.group("amount").replace(" ", "")
    if raw in {"—", "–", "-"}:
        return Decimal(0)
    # SEC tables sometimes put an accounting parenthesis in a separate HTML
    # cell, leaving the numeric cell with only its opening or closing half.
    negative = raw.startswith("(") or raw.endswith(")")
    raw = raw.strip("()").replace(",", "")
    if raw.startswith("-"):
        negative = not negative
        raw = raw[1:]
    try:
        parsed = Decimal(raw)
    except InvalidOperation:
        return None
    return -parsed if negative else parsed


def _year_columns(rows: list[list[str]], fiscal_year: int) -> set[int]:
    columns: set[int] = set()
    for row_index, row in enumerate(rows[:10]):
        joined = " ".join(row).casefold()
        header_like = re.search(r"\b(?:year|ended|as of|balances)\b", joined)
        if not header_like and len(YEAR_RE.findall(joined)) < 2:
            continue
        for column, cell in enumerate(row):
            if column == 0:
                continue
            if str(fiscal_year) in YEAR_RE.findall(cell):
                columns.add(column)
    return columns


def _table_scale(table: Tag, grid: list[list[str]]) -> tuple[Decimal, str] | None:
    snippets = [" ".join(" ".join(row) for row in grid)]
    for sibling in list(table.previous_siblings)[:4]:
        if isinstance(sibling, Tag):
            snippets.append(_text(sibling)[:300])
        elif str(sibling).strip():
            snippets.append(re.sub(r"\s+", " ", str(sibling).strip())[:300])
    text = " ".join(snippets).casefold()
    if re.search(r"\bin\s+millions\b", text):
        return Decimal(1_000_000), "USD millions"
    if re.search(r"\bin\s+thousands\b", text):
        return Decimal(1_000), "USD thousands"
    if re.search(r"\bin\s+billions\b", text):
        return Decimal(1_000_000_000), "USD billions"
    if re.search(r"\bin\s+dollars\b|\b(?:usd|\$)\b", text):
        return Decimal(1), "USD"
    return None


def _statement_date(label: str):
    match = re.search(
        r"\b([A-Z][a-z]{2,8})\s+(\d{1,2}),?\s+(20\d{2})\b", label
    )
    if not match:
        return None
    for pattern in ("%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(" ".join(match.groups()), pattern).date()
        except ValueError:
            continue
    return None


def _parse_row_period(
    grid: list[list[str]],
    *,
    fiscal_year: int,
    period_end: str,
    scale: tuple[Decimal, str],
    table_index: int,
) -> EquityStatement | None:
    target_date = datetime.strptime(period_end, "%Y-%m-%d").date()
    balance_rows: list[tuple[int, Any]] = []
    for index, row in enumerate(grid):
        label = next((cell.strip() for cell in row if cell.strip()), "")
        if BALANCE_ROW_RE.search(label):
            row_date = _statement_date(label)
            if row_date:
                balance_rows.append((index, row_date))
    target_rows = [index for index, row_date in balance_rows if row_date == target_date]
    if not target_rows:
        return None
    if len(target_rows) != 1:
        raise EquityStatementError(
            f"Found multiple ending balance rows for {period_end} in table {table_index}."
        )
    end_index = target_rows[0]
    prior_anchors = [index for index, row_date in balance_rows if index < end_index and row_date < target_date]
    if not prior_anchors:
        return None
    start_index = prior_anchors[-1]
    ending_values = [
        parsed for cell in grid[end_index]
        if (parsed := _amount(cell)) is not None
    ]
    if not ending_values:
        return None
    ending_equity = ending_values[-1] * scale[0]
    components: dict[str, Decimal] = {}
    for row in grid[start_index + 1:end_index]:
        label = next((cell.strip() for cell in row if cell.strip()), "")
        normalized = re.sub(r"\s+", " ", label).casefold()
        if not label or BALANCE_ROW_RE.search(label):
            continue
        if normalized.startswith("total ") or "per share" in normalized:
            continue
        amounts = [
            parsed for cell in row
            if (parsed := _amount(cell)) is not None
        ]
        if not amounts or not re.search(r"[a-z]", label, re.I):
            continue
        candidate = label
        suffix = 2
        while candidate in components:
            candidate = f"{label} (row {suffix})"
            suffix += 1
        components[candidate] = amounts[-1] * scale[0]
    if ending_equity <= 0 or len(components) < 3:
        return None
    if not any("net income" in label.casefold() for label in components):
        return None
    return EquityStatement(
        fiscal_year=fiscal_year,
        period_end=period_end,
        unit=scale[1],
        ending_equity=ending_equity,
        components=components,
        table_index=table_index,
    )


def _parse_candidate(
    table: Tag,
    *,
    table_index: int,
    fiscal_year: int,
    period_end: str,
) -> EquityStatement | None:
    grid = _expand_table(table)
    scale = _table_scale(table, grid)
    if scale is None:
        return None
    row_period = _parse_row_period(
        grid,
        fiscal_year=fiscal_year,
        period_end=period_end,
        scale=scale,
        table_index=table_index,
    )
    if row_period is not None:
        return row_period
    year_columns = _year_columns(grid, fiscal_year)
    if not year_columns:
        return None
    rows: list[tuple[str, Decimal]] = []
    ending_equity: Decimal | None = None
    for row in grid:
        if not row:
            continue
        label = next((cell.strip() for cell in row if cell.strip()), "")
        if not label:
            continue
        values = [
            parsed for index, cell in enumerate(row)
            if index in year_columns
            if (parsed := _amount(cell)) is not None
        ]
        if not values:
            continue
        value = values[-1] * scale[0]
        normalized = re.sub(r"\s+", " ", label).casefold()
        if TOTAL_EQUITY_RE.search(label) or (
            "balances as of" in normalized and "equity" not in normalized
        ):
            ending_equity = value
            continue
        if BALANCE_ROW_RE.search(label):
            continue
        if normalized.startswith("total "):
            continue
        if normalized in {"net income per share", "dividends per share"}:
            continue
        if "per share" in normalized or "per common share" in normalized:
            continue
        if len(label) > 140 or not re.search(r"[a-z]", label, re.I):
            continue
        rows.append((label, value))
    if ending_equity is None or ending_equity <= 0 or len(rows) < 3:
        return None

    components: dict[str, Decimal] = {}
    for label, value in rows:
        candidate = label
        suffix = 2
        while candidate in components:
            candidate = f"{label} (row {suffix})"
            suffix += 1
        components[candidate] = value
    if not any("net income" in label.casefold() for label in components):
        return None
    return EquityStatement(
        fiscal_year=fiscal_year,
        period_end=period_end,
        unit=scale[1],
        ending_equity=ending_equity,
        components=components,
        table_index=table_index,
    )


class EquityStatementExtractor:
    """Extract one annual statement of shareholders' equity, failing closed on ambiguity."""

    def extract(
        self,
        html: str,
        *,
        fiscal_year: int,
        period_end: str,
    ) -> EquityStatement:
        if not html or not html.strip():
            raise EquityStatementError("Filing HTML cannot be empty.")
        if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", period_end):
            raise EquityStatementError("period_end must be an ISO calendar date.")
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[EquityStatement] = []
        for index, table in enumerate(soup.find_all("table"), start=1):
            result = _parse_candidate(
                table,
                table_index=index,
                fiscal_year=fiscal_year,
                period_end=period_end,
            )
            if result:
                candidates.append(result)
        if not candidates:
            raise EquityStatementError(
                f"No complete, period-matched equity statement was found for FY{fiscal_year}."
            )
        if len(candidates) != 1:
            raise EquityStatementError(
                f"Found {len(candidates)} possible equity statements for FY{fiscal_year}; refusing to choose ambiguously."
            )
        return candidates[0]
