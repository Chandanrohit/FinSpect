from finspect.edgar import (
    EdgarClient,
    SubmissionService,
    XBRLService,
)


def main():
    client = EdgarClient(
        user_agent=(
            "FinSpect/0.1 "
            "your-email@example.com"
        )
    )

    submissions = SubmissionService(client)
    xbrl = XBRLService(client)

    # NVIDIA CIK
    cik = "1045810"

    # -------------------------
    # 1. Company submissions
    # -------------------------

    company = submissions.get_company_submissions(
        cik
    )

    print("Company:")
    print(company["name"])

    # -------------------------
    # 2. Find 10-K filings
    # -------------------------

    filings = submissions.get_recent_filings(
        cik,
        form="10-K",
    )

    print("\nRecent 10-K filings:")

    for filing in filings[:5]:
        print(
            filing["filing_date"],
            filing["accession_number"],
            filing["primary_document"],
        )

    # -------------------------
    # 3. XBRL company facts
    # -------------------------

    facts = xbrl.get_company_facts(cik)

    print("\nXBRL taxonomies:")

    for taxonomy in facts["facts"]:
        print(taxonomy)

    # -------------------------
    # 4. One XBRL concept
    # -------------------------

    revenue = xbrl.get_company_concept(
        cik=cik,
        taxonomy="us-gaap",
        concept=(
            "RevenueFromContractWithCustomer"
            "ExcludingAssessedTax"
        ),
    )

    print("\nRevenue concept:")
    print(revenue["label"])

    print("\nAvailable units:")

    for unit in revenue["units"]:
        print(unit)


if __name__ == "__main__":
    main()