
from finspect.edgar import EdgarClient, XBRLService


def main() -> None:
    client = EdgarClient(
        user_agent="FinSpect/0.1 chandanrohot@gmail.com"
    )
    xbrl = XBRLService(client)

    cik = "1045810"
    concept = "RevenueFromContractWithCustomerExcludingAssessedTax"

    revenue = xbrl.get_company_concept(
        cik=cik,
        taxonomy="us-gaap",
        concept=concept,
    )

    print("Company:", revenue["entityName"])
    print("Concept:", revenue["label"])
    print("Units:", list(revenue["units"].keys()))

    # Inspect the most recent reported facts.
    for unit, facts in revenue["units"].items():
        print(f"\nUnit: {unit}")

        for fact in facts[-10:]:
            print({
                "value": fact.get("val"),
                "start": fact.get("start"),
                "end": fact.get("end"),
                "fiscal_year": fact.get("fy"),
                "fiscal_period": fact.get("fp"),
                "form": fact.get("form"),
                "filed": fact.get("filed"),
                "accession_number": fact.get("accn"),
            })


if __name__ == "__main__":
    main()
