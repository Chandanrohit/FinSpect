
from finspect.edgar import EdgarClient, XBRLService


def main() -> None:
    client = EdgarClient(
        user_agent="FinSpect/0.1 chandanrohot@gmail.com"
    )
    xbrl = XBRLService(client)

    response = xbrl.get_company_concept(
        cik="1045810",
        taxonomy="us-gaap",
        concept="RevenueFromContractWithCustomerExcludingAssessedTax",
    )

    for unit, facts in response.get("units", {}).items():
        print(f"\nUNIT: {unit}")
        print(f"Total records: {len(facts)}")

        # Sort by filing date to inspect the newest records first.
        recent_facts = sorted(
            facts,
            key=lambda fact: (
                fact.get("filed", ""),
                fact.get("accn", ""),
            ),
            reverse=True,
        )

        for fact in recent_facts[:30]:
            print({
                "start": fact.get("start"),
                "end": fact.get("end"),
                "value": fact.get("val"),
                "form": fact.get("form"),
                "filed": fact.get("filed"),
                "fiscal_year": fact.get("fy"),
                "fiscal_period": fact.get("fp"),
                "accession_number": fact.get("accn"),
            })


if __name__ == "__main__":
    main()
