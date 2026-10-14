"""Retrieve relevant narrative passages from SEC filing sections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class NarrativePassage:
    """A relevant passage from a filing."""

    section: str
    text: str
    relevance_score: int
    accession_number: str | None = None
    filing_url: str | None = None


SECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "risk_factors": (
        "risk factor",
        "regulatory",
        "export control",
        "government regulation",
        "compliance",
        "geopolitical",
        "restriction",
        "uncertainty",
    ),
    "legal_proceedings": (
        "legal proceeding",
        "litigation",
        "lawsuit",
        "claim",
        "investigation",
        "contingency",
        "settlement",
    ),
    "management_discussion": (
        "management's discussion",
        "management’s discussion",
        "operating results",
        "liquidity",
        "cash flows",
        "revenue growth",
        "market risk",
    ),
    "market_risk": (
        "market risk",
        "interest rate",
        "foreign currency",
        "exchange rate",
        "sensitivity analysis",
        "equity price risk",
    ),
    "business": (
        "business",
        "data center",
        "geographic",
        "customer concentration",
        "supply chain",
        "competition",
    ),
}


def _normalize(text: str) -> str:
    """Normalize whitespace without changing the source wording."""
    return re.sub(r"\s+", " ", text).strip()


def _split_passages(text: str, max_chars: int = 1200) -> list[str]:
    """Split section text into bounded, paragraph-aware passages."""
    if max_chars < 100:
        raise ValueError("max_chars must be at least 100")

    paragraphs = [
        _normalize(part)
        for part in re.split(r"\n\s*\n", text)
        if _normalize(part)
    ]

    passages: list[str] = []
    current = ""

    for paragraph in paragraphs:
        # Split unusually long paragraphs so one passage stays bounded.
        chunks = [
            paragraph[i : i + max_chars]
            for i in range(0, len(paragraph), max_chars)
        ]

        for chunk in chunks:
            if not current:
                current = chunk
            elif len(current) + 1 + len(chunk) <= max_chars:
                current = f"{current} {chunk}"
            else:
                passages.append(current)
                current = chunk

    if current:
        passages.append(current)

    return passages


class NarrativeRetriever:
    """Retrieve relevant passages from already-extracted filing sections."""

    def __init__(self, max_passage_chars: int = 1200) -> None:
        if max_passage_chars < 100:
            raise ValueError("max_passage_chars must be at least 100")
        self.max_passage_chars = max_passage_chars

    def retrieve(
        self,
        sections: dict[str, str],
        query: str,
        *,
        top_k: int = 5,
        accession_number: str | None = None,
        filing_url: str | None = None,
    ) -> list[NarrativePassage]:
        """Return passages ranked by query and section keyword matches."""
        if not query.strip():
            raise ValueError("query must not be empty")
        if top_k < 1:
            raise ValueError("top_k must be at least 1")

        query_terms = {
            term.lower()
            for term in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", query)
        }

        results: list[NarrativePassage] = []

        for section, source_text in sections.items():
            if not source_text or not source_text.strip():
                continue

            section_key = section.lower()
            section_terms = set(SECTION_KEYWORDS.get(section_key, ()))

            for passage in _split_passages(
                source_text, max_chars=self.max_passage_chars
            ):
                passage_lower = passage.lower()

                # Count query-term matches and known section-topic matches.
                query_score = sum(
                    1 for term in query_terms if term in passage_lower
                )
                topic_score = sum(
                    2 for term in section_terms if term in passage_lower
                )

                score = query_score + topic_score
                if score == 0:
                    continue

                results.append(
                    NarrativePassage(
                        section=section,
                        text=passage,
                        relevance_score=score,
                        accession_number=accession_number,
                        filing_url=filing_url,
                    )
                )

        # Stable ordering: highest score first, then section and passage text.
        results.sort(
            key=lambda item: (
                -item.relevance_score,
                item.section,
                item.text,
            )
        )
        return results[:top_k]