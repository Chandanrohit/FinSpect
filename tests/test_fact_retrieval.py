
from finspect.edgar import EdgarClient, XBRLService
from finspect.edgar.facts import FinancialFactRetriever


def main() -> None:
    client = EdgarClient(
        user_agent="FinSpect/0.1 chandanrohot@gmail.com"
    )
    xbrl = XBRLService(client)
    retriever = FinancialFactRetriever(xbrl)

    fact = retriever.get_fact(
        cik="1045810",
        taxonomy="us-gaap",
        concept="RevenueFromContractWithCustomerExcludingAssessedTax",
        start_date="2021-02-01",
        end_date="2022-01-30",
        form="10-K",
        unit="USD",
    )

    print("Selected financial fact:")
    for key, value in fact.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
