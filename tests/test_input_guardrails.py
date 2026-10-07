import pytest
from pydantic import ValidationError

from claims.models import ClaimInput, SearchFilters, redact_personal_data


def claim(**override):
    base = {
        "description": "A burst pipe flooded my kitchen overnight; invoice and photos available.",
        "claim_type": "home",
        "state": "FL",
        "incident_date": "2026-09-04",
        "claim_filed_date": "2026-09-06",
        "claim_amount": 31000,
        "deductible": 2500,
        "previous_claims_count": 1,
        "policyholder_tenure_years": 7,
    }
    return ClaimInput.model_validate(base | override)


@pytest.mark.parametrize("state", ["ZZ", "XX", "AA", "QQ", "PR"])
def test_state_must_be_a_real_us_state_or_dc(state):
    with pytest.raises(ValidationError, match="US state"):
        claim(state=state)
    with pytest.raises(ValidationError, match="US state"):
        SearchFilters(state=state)


@pytest.mark.parametrize("state", ["TX", "CA", "DC", "AK", "ME", "WY"])
def test_every_us_state_and_dc_is_accepted(state):
    assert claim(state=state).state == state
    assert SearchFilters(state=state).state == state


def test_a_missing_state_filter_is_still_allowed():
    assert SearchFilters().state is None


@pytest.mark.parametrize(
    "description",
    [" " * 10, "\t\n" * 8, "!@#$%^&*()_+", "0123456789", "1234 5678 90", "ab ----------"],
)
def test_blank_numeric_or_symbol_only_descriptions_are_refused(description):
    with pytest.raises(ValidationError, match="Describe the incident"):
        claim(description=description)


def test_descriptions_are_trimmed_and_non_latin_text_counts_as_words():
    assert claim(description="   Burst pipe flooded the kitchen.   ").description == (
        "Burst pipe flooded the kitchen."
    )
    assert claim(description="水管破裂导致厨房被淹 burst pipe").description.startswith("水管")


def test_personal_identifiers_are_masked_before_anything_is_stored_or_sent():
    text = (
        "Thief stole my laptop. SSN 123-45-6789, card 4111 1111 1111 1111, "
        "email jane.doe@example.com, phone (206) 555-0199."
    )
    masked = claim(description=text).description
    for leaked in ("123-45-6789", "4111", "jane.doe", "555-0199"):
        assert leaked not in masked
    for token in ("[SSN REDACTED]", "[CARD REDACTED]", "[EMAIL REDACTED]", "[PHONE REDACTED]"):
        assert token in masked
    assert "Thief stole my laptop." in masked


@pytest.mark.parametrize(
    "text",
    [
        "Filed 2026-09-04 2026-09-06 with estimate of $140,000.00 and policy POL-100082395.",
        "Claim CLM-0015151127 for 31000.74 dollars; VIN 1HGCM82633A004352 was inspected.",
        "Order 4111111111111112 is not a valid card number and must be left alone.",
        "Repairs cost 12,345,678 over 2026-08-20 to 2026-09-03.",
    ],
)
def test_ordinary_numbers_dates_and_ids_are_not_masked(text):
    assert redact_personal_data(text) == text


@pytest.mark.parametrize("card", ["4111111111111111", "4111-1111-1111-1111", "378282246310005"])
def test_card_numbers_are_masked_in_common_layouts(card):
    assert redact_personal_data(f"paid with {card} today") == "paid with [CARD REDACTED] today"


def test_masking_is_idempotent_so_stored_claims_can_be_revalidated():
    once = claim(description="My SSN is 123-45-6789 and the car was stolen.").description
    assert claim(description=once).description == once
