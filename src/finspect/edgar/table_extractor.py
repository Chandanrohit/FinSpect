
from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag


FINANCIAL_TERMS = {
    "revenue", "sales", "cost of revenue", "gross profit",
    "operating income", "net income", "cash flow",
    "total assets", "total liabilities", "stockholders' equity",
    "balance sheet", "income statement", "cash equivalents",
    "research and development", "earnings per share", "diluted",
    "basic", "year ended", "three months ended",
    "twelve months ended", "fiscal year",
}

NUMBER_PATTERN = re.compile(
    r"""
    \(?\s*[-+]?\$?
    \d[\d,]*(?:\.\d+)?
    \s*%?\s*\)?
    """,
    re.VERBOSE,
)


class FinancialTableExtractor:
    """Extract SEC HTML tables and rank candidates for financial retrieval."""

    def extract(self, html: str) -> list[dict[str, Any]]:
        if not html or not html.strip():
            raise ValueError("Filing HTML cannot be empty.")

        soup = BeautifulSoup(html, "html.parser")
        results: list[dict[str, Any]] = []

        for index, table in enumerate(soup.find_all("table"), start=1):
            rows = self._table_to_grid(table)

            if not rows:
                continue

            text = " ".join(cell for row in rows for cell in row)
            score, reasons = self._score_table(rows, text)

            results.append({
                "table_id": f"table_{index:04d}",
                "rows": rows,
                "row_count": len(rows),
                "column_count": max(len(row) for row in rows),
                "financial_score": score,
                "is_financial_candidate": score >= 3,
                "classification_reasons": reasons,
            })

        return results

    def _table_to_grid(self, table: Tag) -> list[list[str]]:
        """Extract cell text while avoiding cells from nested tables."""
        rows: list[list[str]] = []

        for row in table.find_all("tr"):
            # Ignore rows that belong to a nested table.
            if row.find_parent("table") is not table:
                continue

            cells = [
                cell
                for cell in row.find_all(["th", "td"])
                if cell.find_parent("table") is table
            ]

            values = [
                self._clean_cell(cell.get_text(" ", strip=True))
                for cell in cells
            ]

            if any(values):
                rows.append(values)

        return rows

    @staticmethod
    def _clean_cell(text: str) -> str:
        text = text.replace("\xa0", " ")
        return re.sub(r"\s+", " ", text).strip()

    def _score_table(
        self,
        rows: list[list[str]],
        text: str,
    ) -> tuple[int, list[str]]:
        """Heuristic ranking; the score is not a correctness guarantee."""
        normalized = text.lower()
        reasons: list[str] = []
        score = 0

        matched_terms = sorted(
            term for term in FINANCIAL_TERMS
            if term in normalized
        )
        if matched_terms:
            score += 2
            reasons.append(
                "financial terminology: " + ", ".join(matched_terms[:5])
            )

        numeric_cells = sum(
            1
            for row in rows
            for cell in row
            if NUMBER_PATTERN.search(cell)
        )
        if numeric_cells >= 4:
            score += 2
            reasons.append(f"{numeric_cells} cells contain numeric patterns")
        elif numeric_cells >= 2:
            score += 1
            reasons.append(f"{numeric_cells} cells contain numeric patterns")

        max_columns = max(len(row) for row in rows)
        if len(rows) >= 3 and max_columns >= 3:
            score += 1
            reasons.append("multi-row, multi-column structure")

        if re.search(r"\b(20\d{2}|19\d{2})\b", normalized):
            score += 1
            reasons.append("contains year-like values")

        if len(rows) == 1 or max_columns <= 1:
            score -= 2
            reasons.append("likely layout or single-column table")

        return score, reasons
