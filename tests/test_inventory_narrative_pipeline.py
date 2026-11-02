from finspect.edgar.filings import FilingRetriever, FilingRetrievalError
from finspect.edgar.parser import FilingParser


class Submissions:
    def __init__(self, filings):
        self.filings = filings
        self.requested = None

    def get_recent_filings(self, *, cik, form):
        assert str(cik).zfill(10) == "0000000001"
        assert form == "10-K"
        return self.filings

    def get_filing_html(self, *, cik, accession_number, primary_document):
        self.requested = (cik, accession_number, primary_document)
        return "<html>filing</html>"


def test_exact_filing_retrieval_uses_requested_accession():
    submissions = Submissions([
        {"form": "10-K", "filing_date": "2025-01-01", "accession_number": "new", "primary_document": "new.htm"},
        {"form": "10-K", "filing_date": "2024-01-01", "accession_number": "requested", "primary_document": "target.htm"},
    ])

    filing = FilingRetriever(submissions).get_filing(
        cik=1, accession_number="requested", form="10-K"
    )

    assert filing["accession_number"] == "requested"
    assert filing["html"] == "<html>filing</html>"
    assert submissions.requested == (1, "requested", "target.htm")


def test_exact_filing_retrieval_fails_closed_when_accession_missing():
    retriever = FilingRetriever(Submissions([]))
    try:
        retriever.get_filing(cik=1, accession_number="missing")
    except FilingRetrievalError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("Missing accession should not select another filing")


def test_filing_parser_preserves_paragraph_boundaries_in_item_sections():
    parsed = FilingParser().parse(
        "<html><body><p>Item 7. Management's Discussion and Analysis</p>"
        "<p>Inventory increased due to demand changes.</p>"
        "<p>Supply constraints also affected the balance.</p></body></html>"
    )
    item7 = next(section for section in parsed["sections"] if section["heading"].startswith("ITEM 7"))
    assert "\n\n" in item7["text"]
    assert "Inventory increased" in item7["text"]
