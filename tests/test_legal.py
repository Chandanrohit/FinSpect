import pytest

from finspect.edgar.legal import LegalDisclosureError, LegalProceedingsExtractor


def test_extracts_nvidia_lawsuit_and_unestimated_possible_loss():
    html = """
    <p>ITEM 3. LEGAL PROCEEDINGS</p>
    <p>Please see Note 12 for a discussion of our legal proceedings.</p>
    <p>ITEM 15. EXHIBITS AND FINANCIAL STATEMENT SCHEDULES</p>
    <p>NOTE 12 - COMMITMENTS AND CONTINGENCIES</p>
    <p>Litigation</p>
    <p>Plaintiffs seek unspecified damages in the securities class action lawsuit concerning alleged statements about channel inventory.</p>
    <p>Accounting for Loss Contingencies</p>
    <p>As of January 26, 2025, there are no accrued contingent liabilities because liabilities are reasonably possible, not probable. Any possible loss or range of loss cannot be reasonably estimated at this time.</p>
    <p>NOTE 13 - INCOME TAXES</p>
    <p>Other text about tax accounting.</p>
    """
    result = LegalProceedingsExtractor().extract(html, fiscal_year=2025)

    assert result.fiscal_year == 2025
    assert any("securities class action" in text for text in result.proceeding_excerpts)
    assert any("unspecified damages" in text for text in result.exposure_excerpts)
    assert any("cannot be reasonably estimated" in text for text in result.uncertainty_excerpts)
    assert result.source_sections[0].startswith("ITEM 3")


def test_extracts_accrued_and_possible_additional_microsoft_loss_exposure():
    html = """
    <p>ITEM 3. LEGAL PROCEEDINGS</p>
    <p>Refer to Note 14 - Contingencies for legal proceedings.</p>
    <p>ITEM 8. FINANCIAL STATEMENTS</p>
    <p>NOTE 14 - CONTINGENCIES</p>
    <p>Irish Data Protection Commission Matter</p>
    <p>LinkedIn appealed a final decision assessing a fine; the next hearing is scheduled for December 2025.</p>
    <p>Other Contingencies</p>
    <p>We are subject to a variety of claims and suits. Although management believes resolving them will not have a material adverse impact, these matters are subject to inherent uncertainties.</p>
    <p>As of June 30, 2025, we accrued aggregate legal liabilities of $541 million. Adverse outcomes could reach approximately $600 million beyond recorded amounts and are reasonably possible.</p>
    <p>NOTE 15 - STOCKHOLDERS' EQUITY</p>
    <p>Other notes do not concern lawsuits.</p>
    """
    result = LegalProceedingsExtractor().extract(html, fiscal_year=2025)

    assert any("LinkedIn appealed" in text for text in result.proceeding_excerpts)
    assert any("$541 million" in text and "$600 million" in text for text in result.exposure_excerpts)
    assert any("reasonably possible" in text for text in result.uncertainty_excerpts)
    assert all("Other notes do not concern" not in text for text in result.proceeding_excerpts)


def test_extracts_apple_fine_and_separates_unresolved_contingency():
    html = """
    <p>ITEM 3. LEGAL PROCEEDINGS</p>
    <p>Digital Markets Act Investigations</p>
    <p>The Commission fined the Company €500 million. The Company appealed the decision.</p>
    <p>A separate investigation could result in fines up to 10% of annual worldwide net sales.</p>
    <p>ITEM 8. FINANCIAL STATEMENTS</p>
    <p>NOTE 12 - COMMITMENTS, CONTINGENCIES AND SUPPLY CONCENTRATIONS</p>
    <p>Contingencies</p>
    <p>The Company is subject to legal proceedings whose outcome is inherently uncertain.</p>
    <p>Management believes there is no reasonable possibility of a material loss or loss greater than recorded accruals.</p>
    <p>NOTE 13 - SEGMENT INFORMATION</p>
    <p>Unrelated paragraph.</p>
    """
    result = LegalProceedingsExtractor().extract(html, fiscal_year=2025)

    assert any("€500 million" in text for text in result.exposure_excerpts)
    assert any("10% of annual worldwide net sales" in text for text in result.exposure_excerpts)
    assert any("outcome is inherently uncertain" in text for text in result.uncertainty_excerpts)


def test_fails_closed_without_item3_contingency_note_or_uncertainty():
    extractor = LegalProceedingsExtractor()
    with pytest.raises(LegalDisclosureError, match="Item 3"):
        extractor.extract("<p>ITEM 8. FINANCIAL STATEMENTS</p>", fiscal_year=2025)
    with pytest.raises(LegalDisclosureError, match="loss uncertainty"):
        extractor.extract(
            "<p>ITEM 3. LEGAL PROCEEDINGS</p><p>We have no lawsuits.</p>",
            fiscal_year=2025,
        )


def test_allows_complete_item3_disclosures_when_no_contingency_note_is_needed():
    html = """
    <p>ITEM 3. LEGAL PROCEEDINGS</p>
    <p>A lawsuit remains pending. The outcome is uncertain and the company cannot reasonably estimate possible loss.</p>
    <p>ITEM 4. MINE SAFETY DISCLOSURES</p>
    <p>Not applicable.</p>
    """
    result = LegalProceedingsExtractor().extract(html, fiscal_year=2025)
    assert result.proceeding_excerpts
    assert result.uncertainty_excerpts
    assert result.source_sections == ("ITEM 3 — LEGAL PROCEEDINGS",)
