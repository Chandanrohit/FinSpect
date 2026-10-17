
from finspect.edgar.facts import FinancialFactRetriever


def test_retriever_respects_original_filing_cutoff():
    class FakeXBRLService:
        def get_company_concept(self, *, cik, taxonomy, concept):
            return {
                "entityName": "Example Corporation",
                "label": "Revenue",
                "units": {
                    "USD": [
                        {
                            "start": "2023-01-30",
                            "end": "2024-01-28",
                            "form": "10-K",
                            "filed": "2024-02-21",
                            "accn": "0001045810-24-000029",
                            "val": 60_922_000_000,
                            "fy": 2024,
                            "fp": "FY",
                        },
                        {
                            # Later comparative filing for the same period.
                            "start": "2023-01-30",
                            "end": "2024-01-28",
                            "form": "10-K",
                            "filed": "2025-02-26",
                            "accn": "0001045810-25-000023",
                            "val": 60_922_000_000,
                            "fy": 2025,
                            "fp": "FY",
                        },
                    ]
                },
            }

    retriever = FinancialFactRetriever(FakeXBRLService())

    fact = retriever.get_fact(
        cik="1045810",
        taxonomy="us-gaap",
        concept="Revenues",
        start_date="2023-01-30",
        end_date="2024-01-28",
        form="10-K",
        unit="USD",
        filed_on_or_before="2024-02-21",
    )

    assert fact["value"] == 60_922_000_000
    assert fact["filing_date"] == "2024-02-21"
    assert fact["accession_number"] == "0001045810-24-000029"
