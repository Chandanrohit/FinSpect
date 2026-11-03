"""Build bounded, non-causal links between financial results and filing risks."""

from __future__ import annotations

from dataclasses import dataclass
import re

from finspect.narrative_retriever import _normalize, _split_passages


@dataclass(frozen=True, slots=True)
class LinkedDisclosure:
    """A management-reported financial passage linked to a related disclosure."""

    theme: str
    management_excerpt: str
    related_section: str
    related_excerpt: str


THEMES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AI infrastructure", ("ai infrastructure", "artificial intelligence infrastructure")),
    ("Tariffs and trade restrictions", ("tariff", "trade restriction", "trade measure")),
    ("Inventory and purchase commitments", ("inventory", "inventories", "purchase commitment", "purchase obligation")),
    ("Export controls", ("export control", "export restriction", "licensing requirement")),
    ("Impairments and asset valuations", ("impairment", "write-down", "fair value")),
    ("Foreign exchange", ("foreign currency", "exchange rate", "currency fluctuation")),
    ("Legal contingencies", ("legal proceeding", "litigation", "contingency", "contingencies")),
    ("Cloud infrastructure", ("cloud infrastructure", "datacenter", "data center", "server capacity")),
    ("Supply chain", ("supply chain", "supplier", "component shortage", "purchase obligations")),
    ("Regulation", ("regulatory", "regulation", "government policy")),
)
_FINANCIAL_SIGNAL = re.compile(
    r"\$|€|£|\b\d+(?:\.\d+)?%|increased|decreased|declined|grew|margin|"
    r"revenue|expense|cost|provision|charge|impairment|cash flow|obligation",
    re.I,
)


def link_material_disclosures(
    sections: dict[str, str], *, max_themes: int = 3
) -> list[LinkedDisclosure]:
    """Find a financial-results excerpt and related non-MD&A excerpt by theme.

    The function surfaces linked source passages; it never concludes that the
    related risk caused the reported result. It fails closed without a theme
    appearing in both Item 7 and another supplied filing section.
    """
    if max_themes < 1:
        raise ValueError("max_themes must be at least 1")
    management = [
        _normalize(passage)
        for passage in _split_passages(sections.get("management_discussion", ""))
        if _FINANCIAL_SIGNAL.search(passage)
    ]
    related = {
        section: [
            _normalize(passage)
            for passage in _split_passages(text)
        ]
        for section, text in sections.items()
        if section != "management_discussion" and text.strip()
    }

    linked: list[LinkedDisclosure] = []
    for label, terms in THEMES:
        candidates = [
            passage for passage in management
            if any(term in passage.casefold() for term in terms)
        ]
        for management_excerpt in candidates:
            match = next((
                (section, passage)
                for section in sorted(related)
                for passage in related[section]
                if any(term in passage.casefold() for term in terms)
            ), None)
            if match:
                disclosure = LinkedDisclosure(
                    label, management_excerpt, match[0], match[1]
                )
                if disclosure not in linked:
                    linked.append(disclosure)
                break
        if len(linked) >= max_themes:
            break
    return linked
