
from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Comment


ITEM_PATTERN = re.compile(
    r"\b(Item\s+\d{1,2}[A-Z]?)\s*[.\-:—]?\s*"
    r"([A-Z][A-Z0-9 ,&()/\-]{2,100})",
    re.IGNORECASE,
)


class FilingParser:
    """Extract readable text, approximate sections, and tables from SEC HTML."""

    def parse(
        self,
        html: str,
        *,
        filing_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not html or not html.strip():
            raise ValueError("Filing HTML cannot be empty.")

        soup = BeautifulSoup(html, "html.parser")

        # Remove non-visible or non-narrative elements.
        for element in soup.find_all(
            ["script", "style", "noscript", "ix:hidden"]
        ):
            element.decompose()

        for comment in soup.find_all(
            string=lambda value: isinstance(value, Comment)
        ):
            comment.extract()

        tables = self._extract_tables(soup)

        # Work on a copy so table extraction remains independent.
        text_soup = BeautifulSoup(str(soup), "html.parser")
        for table in text_soup.find_all("table"):
            table.decompose()

        root = text_soup.body or text_soup
        raw_text = root.get_text("\n", strip=True)
        lines = self._clean_lines(raw_text)

        sections = self._split_sections(lines)

        title = None
        if soup.title:
            title = self._clean_text(soup.title.get_text(" ", strip=True))

        # Some SEC filings have generic or filename-like HTML titles.
        if not title or re.fullmatch(r"nvda[-_]\d{8}", title, re.I):
            title = self._find_document_title(lines)

        return {
            "metadata": filing_metadata or {},
            "title": title,
            "sections": sections,
            "tables": tables,
            "section_count": len(sections),
            "table_count": len(tables),
            "text_line_count": len(lines),
        }

    @staticmethod
    def _clean_text(text: str) -> str:
        text = text.replace("\xa0", " ")
        return re.sub(r"\s+", " ", text).strip()

    def _clean_lines(self, raw_text: str) -> list[str]:
        lines = []
        for line in raw_text.splitlines():
            line = self._clean_text(line)
            if not line:
                continue

            # Drop common standalone Inline XBRL metadata fragments.
            if re.fullmatch(
                r"(?:iso4217|xbrli|xbrl|dei|us-gaap):[A-Za-z0-9_:.-]+",
                line,
                re.I,
            ):
                continue

            lines.append(line)

        return lines

    def _split_sections(
        self,
        lines: list[str],
    ) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        current_heading = "Document introduction"
        current_lines: list[str] = []

        def flush() -> None:
            text = self._clean_text(" ".join(current_lines))
            if text:
                sections.append({
                    "section_id": f"section_{len(sections) + 1:04d}",
                    "heading": current_heading,
                    "text": text,
                })
            current_lines.clear()

        for line in lines:
            match = ITEM_PATTERN.search(line)

            if match:
                item = match.group(1).upper()
                heading_text = self._clean_text(match.group(2))
                heading = f"{item} — {heading_text}"

                # Avoid splitting on the same item label repeated in body text.
                if heading.lower() != current_heading.lower():
                    flush()
                    current_heading = heading
                    remainder = line[match.end():].strip(" .:-—")
                    if remainder:
                        current_lines.append(remainder)
                    continue

            current_lines.append(line)

        flush()
        return sections

    def _find_document_title(self, lines: list[str]) -> str | None:
        for line in lines[:80]:
            upper = line.upper()
            if "ANNUAL REPORT" in upper:
                return line[:250]
            if "QUARTERLY REPORT" in upper:
                return line[:250]
        return None

    def _extract_tables(
        self,
        soup: BeautifulSoup,
    ) -> list[dict[str, Any]]:
        tables: list[dict[str, Any]] = []

        for table in soup.find_all("table"):
            rows: list[list[str]] = []

            for row in table.find_all("tr"):
                cells = row.find_all(["th", "td"])

                values = [
                    self._clean_text(cell.get_text(" ", strip=True))
                    for cell in cells
                ]

                if any(values):
                    rows.append(values)

            # Exclude empty tables, but retain tables even if they have
            # only one row; some filing tables are used for layout.
            if rows:
                tables.append({
                    "table_id": f"table_{len(tables) + 1:04d}",
                    "rows": rows,
                    "row_count": len(rows),
                    "column_count": max(len(row) for row in rows),
                })

        return tables

