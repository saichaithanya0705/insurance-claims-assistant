"""Hand-authored fixtures; not rows or narratives from the published dataset."""

DEMO_CASES = [
    {
        "id": "auto-ready",
        "title": "Auto: repair evidence available",
        "claim": {
            "description": "My car was rear-ended at a junction. A repair estimate is available.",
            "claim_type": "auto",
            "state": "TX",
            "incident_date": "2026-09-01",
            "claim_filed_date": "2026-09-02",
            "claim_amount": 8500,
            "deductible": 500,
            "previous_claims_count": 0,
            "policyholder_tenure_years": 4,
            "provided_documents": ["incident statement", "repair estimate"],
        },
    },
    {
        "id": "theft-gap",
        "title": "Auto theft: missing evidence and late report",
        "claim": {
            "description": "My car was stolen from the parking area. I have not supplied a police report.",
            "claim_type": "auto",
            "state": "CA",
            "incident_date": "2026-08-01",
            "claim_filed_date": "2026-08-18",
            "claim_amount": 42000,
            "deductible": 1000,
            "previous_claims_count": 3,
            "policyholder_tenure_years": 0.5,
            "provided_documents": ["incident statement"],
        },
    },
    {
        "id": "home-conflict",
        "title": "Home: conflicting descriptions",
        "claim": {
            "description": "My home has water damage. A burst pipe caused it; another statement says there was no burst pipe.",
            "claim_type": "home",
            "state": "FL",
            "incident_date": "2026-09-04",
            "claim_filed_date": "2026-09-06",
            "claim_amount": 67000,
            "deductible": 2500,
            "previous_claims_count": 1,
            "policyholder_tenure_years": 7,
            "provided_documents": ["incident statement"],
        },
    },
    {
        "id": "unknown",
        "title": "Ambiguous claim: classification needs review",
        "claim": {
            "description": "I suffered a loss yesterday and need help figuring out the claim type.",
            "claim_type": None,
            "state": "NY",
            "incident_date": "2026-09-15",
            "claim_filed_date": "2026-09-16",
            "claim_amount": 2500,
            "deductible": 250,
            "previous_claims_count": 0,
            "policyholder_tenure_years": 2,
            "provided_documents": [],
        },
    },
]


def fixture_history():
    rows = []
    descriptions = {
        "auto": "Vehicle damage incident; repair estimate reviewed",
        "home": "Home water damage incident; property assessment reviewed",
        "renters": "Tenant personal belongings damaged",
        "property": "Insured property damaged; inspection available",
        "business": "Business premises loss; inventory assessment available",
    }
    for i, (kind, description) in enumerate(descriptions.items()):
        for j, state in enumerate(("TX", "CA", "FL", "NY")):
            rows.append(
                {
                    "claim_id": f"FIX-{i}-{j}",
                    "policy_id": f"FIX-POL-{i}-{j}",
                    "claim_type": kind,
                    "state": state,
                    "claim_amount": 5000 + i * 13000 + j * 7500,
                    "deductible": 500 + i * 250,
                    "previous_claims_count": j,
                    "policyholder_tenure_years": 1 + j * 2,
                    "incident_date": "2025-06-01",
                    "claim_filed_date": "2025-06-03",
                    "claim_status": "approved" if j % 2 == 0 else "denied",
                    "days_to_resolution": 10 + j * 5,
                    "description": description,
                    "provenance": "synthetic_fixture",
                }
            )
    return rows
