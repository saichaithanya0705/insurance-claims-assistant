import pytest

from claims.corpus.cards import (
    ALIAS,
    amount_band,
    claim_alias,
    claim_card_text,
    claim_id_from_alias,
    claim_ids_in_text,
    delay_band,
    history_band,
    is_card_chunk,
    region_token,
    tenure_band,
)

ROW = {
    "claim_type": "auto",
    "state": "TX",
    "claim_amount": 8500,
    "deductible": 500,
    "previous_claims_count": 0,
    "policyholder_tenure_years": 4,
    "incident_date": "2026-09-01",
    "claim_filed_date": "2026-09-02",
    "claim_status": "approved",
    "days_to_resolution": 12.0,
}


def test_alias_round_trips_and_is_lowercase_letters_only():
    alias = claim_alias("CLM-0000000012")
    assert alias == "claimref_aaaaaaaabc"
    assert alias.islower() and not any(c.isdigit() for c in alias)
    assert claim_id_from_alias(alias) == "CLM-0000000012"
    for number in (0, 1, 99_999_999, 42_424_242):
        claim_id = f"CLM-{number:010d}"
        assert claim_id_from_alias(claim_alias(claim_id)) == claim_id


@pytest.mark.parametrize("bad", ["CLM-12", "POL-100297760", "claimref_aaaaaaaabc", ""])
def test_alias_rejects_non_claim_ids(bad):
    with pytest.raises(ValueError):
        claim_alias(bad)


def test_ids_are_found_in_order_without_duplicates_and_legacy_ids_still_count():
    text = "x claimref_aaaaaaaade then claimref_aaaaaaaabc, again claimref_aaaaaaaade; CLM-0000000099"
    assert claim_ids_in_text(text) == ["CLM-0000000034", "CLM-0000000012", "CLM-0000000099"]
    assert claim_ids_in_text("") == [] and claim_ids_in_text(None) == []
    # Upper-case lookalikes (what Synapt's masking produced) are not misread as aliases.
    assert ALIAS.search("CLMREF-AAAAAAAABC") is None


def test_region_tokens_are_opaque_unique_and_never_a_place_name():
    from claims.corpus.cards import STATE_NAMES

    tokens = {code: region_token(code) for code in STATE_NAMES}
    assert len(set(tokens.values())) == len(STATE_NAMES)
    assert all(t.startswith("regionkey_") and t.islower() and t[10:].isalpha() for t in tokens.values())
    with pytest.raises(ValueError):
        region_token("ZZ")


def test_masking_safe_card_hides_state_but_readable_card_names_it():
    readable = claim_card_text(ROW)
    safe = claim_card_text(ROW, masking_safe=True)
    assert "Texas (TX)" in readable and "TX" not in safe and "Texas" not in safe
    assert region_token("TX") in safe
    assert "no prior claims" in safe and "5,000-10,000" in safe and "Outcome approved after 12 days" in safe
    # A query must never contain the outcome it is trying to predict.
    assert "Outcome" not in claim_card_text(ROW, include_outcome=False, masking_safe=True)


def test_open_claims_describe_status_not_an_outcome():
    row = ROW | {"claim_status": "under_review", "days_to_resolution": 8.0}
    assert "under review; no final outcome yet" in claim_card_text(row)
    assert "Outcome" not in claim_card_text(row)


def test_bands():
    assert amount_band(500) == "under 1,000"
    assert amount_band(8500) == "5,000-10,000"
    assert amount_band(250_000) == "over 250,000"
    assert tenure_band(0.5) == "under 1 year" and tenure_band(30) == "over 20 years"
    assert delay_band(0) == "same day" and delay_band(5) == "4-8 days"
    assert [history_band(n) for n in (0, 1, 3, 9)] == [
        "no prior claims",
        "one prior claim",
        "a few prior claims",
        "many prior claims",
    ]


def test_card_chunks_are_recognised_even_if_the_marker_line_is_lost():
    assert is_card_chunk("claim_ref: claimref_aaaaaaaabc\nauto claim")
    assert is_card_chunk("## history:claimref_aaaaaaaabc ...")
    assert not is_card_chunk("For an auto claim, request an incident statement.")
