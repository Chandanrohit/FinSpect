
from finspect.edgar import EdgarClient, SubmissionService
from finspect.edgar.filings import FilingRetriever
from finspect.edgar.parser import FilingParser


def main() -> None:
    client = EdgarClient(
        user_agent="FinSpect/0.1 chandanrohot@gmail.com"
    )

    submissions = SubmissionService(client)
    retriever = FilingRetriever(submissions)
    parser = FilingParser()

    filing = retriever.get_latest_filing(
        cik="1045810",
        form="10-K",
    )

    document = parser.parse(
        filing["html"],
        filing_metadata={
            "cik": filing["cik"],
            "form": filing["form"],
            "filing_date": filing["filing_date"],
            "report_date": filing["report_date"],
            "accession_number": filing["accession_number"],
            "primary_document": filing["primary_document"],
        },
    )

    print("Filing:", document["metadata"]["primary_document"])
    print("Title:", document["title"])
    print("Sections:", document["section_count"])
    print("Tables:", document["table_count"])

    print("\n--- First 3 sections ---")
    for section in document["sections"][:3]:
        print("\nID:", section["section_id"])
        print("Heading:", section["heading"])
        print("Text preview:", section["text"][:400])

    print("\n--- First 2 tables ---")
    for table in document["tables"][:2]:
        print("\nID:", table["table_id"])
        print("Rows:", table["row_count"])
        for row in table["rows"][:5]:
            print(row)


if __name__ == "__main__":
    main()
