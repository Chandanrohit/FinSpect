from finspect.material_disclosures import link_material_disclosures


def test_links_reported_result_to_related_risk_without_causal_assertion():
    sections = {
        "management_discussion": (
            "Microsoft Cloud gross margin percentage decreased to 69% driven by the impact "
            "of scaling our AI infrastructure, offset in part by efficiency gains in Azure."
        ),
        "risk_factors": (
            "The investments we are making in cloud and AI infrastructure will continue "
            "to increase operating costs and may decrease operating margins."
        ),
    }

    linked = link_material_disclosures(sections)

    assert linked
    assert linked[0].theme == "AI infrastructure"
    assert "69%" in linked[0].management_excerpt
    assert "operating costs" in linked[0].related_excerpt
    assert linked[0].related_section == "risk_factors"


def test_returns_no_synthesis_without_shared_cross_section_topic():
    sections = {
        "management_discussion": "Revenue increased by 12% during the fiscal year.",
        "risk_factors": "Our offices may be affected by severe weather events.",
    }

    assert link_material_disclosures(sections) == []
