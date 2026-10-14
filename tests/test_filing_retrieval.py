
from finspect.edgar import EdgarClient, SubmissionService
from finspect.edgar.filings import FilingRetriever


def main() -> None:
    client = EdgarClient(
        user_agent="FinSpect/0.1 your-real-email@example.com"
    )

    submissions = SubmissionService(client)
    retriever = FilingRetriever(submissions)

    filing = retriever.get_latest_filing(
        cik="1045810",
        form="10-K",
    )

    print("Form:", filing["form"])
    print("Filing date:", filing["filing_date"])
    print("Report date:", filing["report_date"])
    print("Accession:", filing["accession_number"])
    print("Primary document:", filing["primary_document"])
    print("HTML characters:", len(filing["html"]))
    print("HTML preview:")
    print(filing["html"][:500])


if __name__ == "__main__":
    main()
