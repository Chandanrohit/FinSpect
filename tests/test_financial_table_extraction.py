
from finspect.edgar import EdgarClient, SubmissionService
from finspect.edgar.filings import FilingRetriever
from finspect.edgar.table_extractor import FinancialTableExtractor


def main() -> None:
    client = EdgarClient(
        user_agent="FinSpect/0.1 chandanrohot@gmail.com"
    )

    submissions = SubmissionService(client)
    retriever = FilingRetriever(submissions)
    extractor = FinancialTableExtractor()

    filing = retriever.get_latest_filing(
        cik="1045810",
        form="10-K",
    )

    tables = extractor.extract(filing["html"])
    candidates = [
        table for table in tables
        if table["is_financial_candidate"]
    ]

    print("Filing:", filing["primary_document"])
    print("Tables extracted:", len(tables))
    print("Financial candidates:", len(candidates))

    print("\n--- Top financial candidates ---")

    for table in sorted(
        candidates,
        key=lambda item: item["financial_score"],
        reverse=True,
    )[:10]:
        print(
            f"\n{table['table_id']} | "
            f"score={table['financial_score']} | "
            f"rows={table['row_count']} | "
            f"columns={table['column_count']}"
        )
        print("Reasons:", table["classification_reasons"])

        for row in table["rows"][:6]:
            print(row[:8])


if __name__ == "__main__":
    main()
