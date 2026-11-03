"""Extract legal-proceeding and loss-contingency disclosures from SEC filings."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .parser import FilingParser


class LegalDisclosureError(ValueError):
    """Raised when a filing does not expose a clear legal disclosure section."""


@dataclass(frozen=True, slots=True)
class LegalProceedingsDisclosure:
    fiscal_year: int
    proceeding_excerpts: tuple[str, ...]
    exposure_excerpts: tuple[str, ...]
    uncertainty_excerpts: tuple[str, ...]
    source_sections: tuple[str, ...]


_NOTE_HEADING = re.compile(
    r"(?im)^\s*note\s+\d+\s*[–—-]\s*[^\n]*(?:contingen|legal proceeding|litigation)[^\n]*"
)
_NEXT_NOTE = re.compile(r"(?im)^\s*note\s+\d+\s*[–—-]")
_LEGAL_TERMS = re.compile(
    r"lawsuit|litigat|plaintiff|claim|legal proceeding|legal liabilit|court|indemnif|fine|damages|contingen|loss",
    re.I,
)
_UNCERTAINTY_TERMS = re.compile(
    r"uncertain|reasonably possible|not probable|cannot (?:be )?reasonably estimated|"
    r"no accrued|not reasonably estimable|no assurance|probable.*reasonably estimable|"
    r"may not be material|management currently believes",
    re.I,
)
_EXPOSURE_TERMS = re.compile(
    r"(?:\$|€|£)\s*\d|\d+(?:\.\d+)?%|unspecified (?:compensatory )?damages|"
    r"(?:loss|liabilit|damages|fine|exposure).{0,50}(?:estimate|range|accru|amount)",
    re.I,
)


def _paragraphs(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", paragraph).strip()
        for paragraph in re.split(r"\n\s*\n", text)
        if paragraph.strip()
    ]


def _contingency_note_blocks(text: str) -> list[str]:
    blocks = []
    headings = list(_NOTE_HEADING.finditer(text))
    for heading in headings:
        next_note = _NEXT_NOTE.search(text, heading.end())
        end = next_note.start() if next_note else len(text)
        blocks.append(text[heading.start():end])
    return blocks


class LegalProceedingsExtractor:
    """Return exact Item 3 and contingency-note excerpts without inferring outcomes."""

    def extract(self, html: str, *, fiscal_year: int) -> LegalProceedingsDisclosure:
        if not html or not html.strip():
            raise ValueError("Filing HTML cannot be empty.")
        if fiscal_year < 1900:
            raise ValueError("fiscal_year must be a valid four-digit year")

        parsed = FilingParser().parse(html)
        item3_sections = [
            section for section in parsed["sections"]
            if section["heading"].upper().startswith("ITEM 3")
        ]
        if not item3_sections:
            raise LegalDisclosureError("The exact 10-K does not expose a readable Item 3 section.")

        note_blocks = []
        for section in parsed["sections"]:
            note_blocks.extend(_contingency_note_blocks(section["text"]))

        source_texts = [section["text"] for section in item3_sections] + note_blocks
        passages = list(dict.fromkeys(
            paragraph
            for text in source_texts
            for paragraph in _paragraphs(text)
            if _LEGAL_TERMS.search(paragraph)
        ))
        if not passages:
            raise LegalDisclosureError("The Item 3 and contingency note contain no legal claim passages.")

        uncertainty = tuple(
            passage for passage in passages if _UNCERTAINTY_TERMS.search(passage)
        )
        exposure = tuple(
            passage for passage in passages if _EXPOSURE_TERMS.search(passage)
        )
        proceedings = tuple(
            passage for passage in passages
            if len(passage) >= 80
        )
        if not uncertainty:
            raise LegalDisclosureError(
                "The exact filing does not expose a clear statement about loss uncertainty."
            )
        return LegalProceedingsDisclosure(
            fiscal_year=fiscal_year,
            proceeding_excerpts=proceedings[:6],
            exposure_excerpts=exposure,
            uncertainty_excerpts=uncertainty,
            source_sections=tuple(
                [section["heading"] for section in item3_sections]
                + (["Contingencies note"] if note_blocks else [])
            ),
        )
