"""The brief must never decide, or hint at, whether a claim is covered: the system has no policy terms."""

import pytest

from claims.investigation.workflow import asserts_coverage_conclusion, validate_brief

CONCLUSIONS = [
    "The claim appears to be covered under the policy.",
    "This claim is likely to be approved.",
    "The theft is not covered because no police report was filed.",
    "The claimant qualifies for payment.",
    "This is a valid claim.",
    "The loss is outside the policy.",
    "This claim is clearly eligible.",
    "Based on similar cases the claim should be paid.",
    "The damage seems claimable.",
    "The incident is probably not covered.",
]

ALLOWED = [
    "Historical outcomes and synthetic examples do not establish coverage or prove fraud.",
    "Verify applicable policy terms with the handler.",
    "Coverage cannot be determined from the supplied facts.",
    "Whether the loss is covered depends on policy wording that the handler must check.",
    "Confirm whether the claim is covered under the policy.",
    "A similar historical claim was approved after 21 days.",
    "Missing submitted document: police report. Confirm applicability with the handler.",
    "Submitted claimed amount is $42,000.00.",
    "The submitted description contains conflicting burst-pipe statements; ask the handler to reconcile them.",
    "Coverage has not been verified, and policy terms were not supplied.",
]


@pytest.mark.parametrize("text", CONCLUSIONS)
def test_coverage_conclusions_are_caught(text):
    assert asserts_coverage_conclusion(text)


@pytest.mark.parametrize("text", ALLOWED)
def test_disclaimers_and_plain_facts_are_allowed(text):
    assert not asserts_coverage_conclusion(text)


def brief(finding_text="Submitted claimed amount is $5,000.00.", reason="Confirm policy version and terms."):
    return {
        "evidence": [{"source_id": "claim:input"}, {"source_id": "procedure-1"}],
        "findings": [{"kind": "fact", "text": finding_text, "source_ids": ["claim:input"]}],
        "recommendations": [{
            "action": "Verify applicable policy terms with the handler",
            "reason": reason,
            "source_ids": ["procedure-1"],
        }],
        "classification": {"needs_review": False},
    }


def checks(result):
    return {c["id"]: c for c in result["checks"]}


def test_a_brief_that_hints_at_coverage_fails_validation_and_blocks_acceptance():
    result = validate_brief(brief("The claim appears covered, so it can proceed."))
    assert result["passed"] is False
    assert checks(result)["coverage_assertion"]["failed"] == 1
    assert any("coverage or eligibility conclusion" in issue for issue in result["issues"])


def test_a_hint_in_a_recommendation_reason_is_caught_too():
    result = validate_brief(brief(reason="The claim is probably valid; request the documents."))
    assert result["passed"] is False and checks(result)["coverage_assertion"]["failed"] == 1


def test_a_neutral_brief_still_passes():
    result = validate_brief(brief())
    assert checks(result)["coverage_assertion"]["failed"] == 0
    assert checks(result)["coverage_assertion"]["inspected"] == 3
    assert result["passed"] is True
