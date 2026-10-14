import pytest

from finspect.narrative_retriever import NarrativeRetriever


@pytest.fixture
def retriever():
    return NarrativeRetriever(max_passage_chars=300)


def test_retrieves_relevant_risk_passage(retriever):
    sections = {
        "risk_factors": (
            "The company faces regulatory restrictions and export control "
            "requirements in certain markets."
        ),
        "business": (
            "The company develops computing products for data centers."
        ),
    }

    results = retriever.retrieve(
        sections,
        "What regulatory and export control risks were disclosed?",
    )

    assert results
    assert results[0].section == "risk_factors"
    assert "export control" in results[0].text.lower()


def test_preserves_filing_provenance(retriever):
    results = retriever.retrieve(
        {
            "legal_proceedings": (
                "The company is subject to litigation and legal claims."
            )
        },
        "What litigation was disclosed?",
        accession_number="0001045810-26-000021",
        filing_url="https://www.sec.gov/Archives/example",
    )

    assert len(results) == 1
    assert results[0].accession_number == "0001045810-26-000021"
    assert results[0].filing_url == "https://www.sec.gov/Archives/example"


def test_irrelevant_text_is_not_returned(retriever):
    results = retriever.retrieve(
        {"business": "The office has several meeting rooms."},
        "What litigation risks were disclosed?",
    )

    assert results == []


def test_top_k_limits_results(retriever):
    sections = {
        "risk_factors": (
            "Regulatory restrictions affect operations. "
            "Export control requirements apply in certain countries. "
            "Government regulation may affect sales."
        )
    }

    results = retriever.retrieve(
        sections,
        "regulatory restrictions export control government regulation",
        top_k=1,
    )

    assert len(results) <= 1


def test_empty_query_is_rejected(retriever):
    with pytest.raises(ValueError, match="query"):
        retriever.retrieve({"risk_factors": "Some text"}, "   ")


def test_invalid_top_k_is_rejected(retriever):
    with pytest.raises(ValueError, match="top_k"):
        retriever.retrieve({"risk_factors": "Some text"}, "regulatory risk", top_k=0)


def test_passages_respect_configured_limit():
    retriever = NarrativeRetriever(max_passage_chars=100)
    sections = {"risk_factors": "regulatory risk " * 100}

    results = retriever.retrieve(sections, "regulatory risk", top_k=10)

    assert results
    assert all(len(item.text) <= 100 for item in results)
