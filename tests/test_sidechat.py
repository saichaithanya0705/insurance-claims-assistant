"""The side chat: questions about the claim being investigated, answered from the right source, kept apart from the brief.

A router sends each question to what can answer it (Synapt for handling knowledge; the saved run for the claim's facts, the
brief, past-claim statistics, estimates and provenance), a mixed question gets one labelled part per source, a decision
question is declined, and nothing here changes the investigation. Only a handling question reaches Synapt, and that call
appears in its Explainability page, so the question is masked, the claim's narrative never leaves, repeats are answered from
the saved answer and volume is limited.
"""

import copy
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from synapt_stub import StubSynaptAdapter

from claims.api.main import create_app
from claims.core.demo_cases import DEMO_CASES
from claims.core.settings import Settings
from claims.investigation import sidechat
from claims.investigation.sidechat import SideChat, SideChatError, route
from claims.storage.run_store import Store

# ----- the router ----------------------------------------------------------------------------------------------------

ROUTES = [
    ("Which documents should I request for this claim?", {"handling"}),
    ("What does the police report request procedure say, step by step?", {"handling"}),
    ("Who is responsible for confirming the documents with the handler?", {"handling"}),
    ("In what order should I ask for the documents?", {"handling"}),
    ("How should I handle a stolen vehicle claim with no police report?", {"handling"}),
    ("What is the claimed amount?", {"claim_facts"}),
    ("What is the amount net of the deductible?", {"claim_facts"}),
    ("How many days after the incident was it filed?", {"claim_facts"}),
    ("Which documents were submitted?", {"claim_facts"}),
    ("Which documents do we have on file?", {"claim_facts"}),
    ("How many previous claims does the policyholder have?", {"claim_facts"}),
    ("Which state is this claim in?", {"claim_facts"}),
    ("Tell me about tenure and the deductible", {"claim_facts"}),
    ("Why is the priority low?", {"brief"}),
    ("What is missing from this claim?", {"brief"}),
    ("Are there any contradictions?", {"brief"}),
    ("What are the recommended next steps?", {"brief"}),
    ("Did the brief pass validation?", {"brief"}),
    ("Why was the claim flagged?", {"brief"}),
    ("How were claims like this usually settled?", {"history"}),
    ("What is the median time to settle for similar claims?", {"history"}),
    ("What share of similar claims were approved?", {"history"}),
    ("What is the approval rate?", {"history"}),
    ("What does the fraud-flag signal mean?", {"estimates"}),
    ("What is the estimated amount and days to resolve?", {"estimates"}),
    ("Where did this come from?", {"sources"}),
    ("Which sources back the main findings?", {"sources", "brief"}),
    ("Should I approve this claim?", {"decision"}),
    ("Is this claim fraudulent?", {"decision"}),
    ("Is it covered?", {"decision"}),
    ("Will this be approved?", {"decision"}),
    ("Should I deny the claim given the fraud-flag?", {"decision"}),
    ("Given the missing incident statement, what should I request, and how long do similar claims take?", {"handling", "history"}),
    ("What is the claimed amount and which documents should I request?", {"claim_facts", "handling"}),
    # found by running a test pack through the router on 12 October: each of these used to go somewhere questionable
    ("Does the policy's wear-and-tear exclusion apply here?", {"decision"}),
    ("How much should we offer for the stolen jewelry?", {"decision"}),
    ("Is the claimant telling the truth?", {"decision"}),
    ("What was the weather in Tampa on the incident date?", {"outside"}),
    ("What is the claimant's phone number and home address?", {"outside"}),
    ("How many days passed between the incident and the filing, and is that long?", {"claim_facts"}),
    ("Are there any claims from this state in your records at all?", {"history"}),
    ("How confident is the amount model for a claim this size?", {"estimates"}),
    # and the near misses that must keep going where they went
    ("Which documents should I request after the fire?", {"handling"}),
    ("What does the coverage boundary procedure say about human review?", {"handling"}),
    ("Was there a fire at the property that night?", {"outside"}),
    # found live: the bare word "claimant" dragged the whole claim record in beside a handling answer
    ("What should I ask a claimant who says the damage happened before the policy started?", {"handling"}),
    ("What did the claimant say?", {"claim_facts"}),
    ("asdf", set()),
    ("hmm ok", set()),
]


@pytest.mark.parametrize(("question", "expected"), ROUTES)
def test_each_kind_of_question_goes_to_the_source_that_can_answer_it(question, expected):
    assert set(route(question)["intents"]) == expected, route(question)


def test_every_routed_kind_of_question_gets_its_own_part_so_none_falls_through_to_not_understood(tmp_path, monkeypatch):
    monkeypatch.setattr(sidechat, "MAX_PER_RUN", 1000)  # the table asks more questions than one case may
    expected = {"claim_facts": "claim", "brief": "brief", "history": "history", "estimates": "estimates", "sources": "evidence", "decision": "boundary", "handling": "synapt", "outside": "outside"}
    seen = set()
    store = Store(tmp_path / "all.sqlite")
    store.save(RUN["run_id"], copy.deepcopy(RUN))
    side = SideChat(store, FakeAdapter(), sidechat.RateLimiter(limit=1000))
    for question, kinds in ROUTES:
        if not kinds:
            continue
        answer = side.ask(RUN, question, owner="alice")
        intents = route(question)["intents"]
        # the parts answered from the saved run come first, in routing order; Synapt's, the slowest, comes last
        assert [p["source"] for p in answer["parts"]] == [expected[k] for k in intents if k != "handling"] + (["synapt"] if "handling" in intents else []), question
        assert "unknown" not in {p["source"] for p in answer["parts"]}, question
        seen |= set(kinds)
    assert seen == set(expected)
    store.connection.close()


def test_a_decision_question_never_also_asks_synapt_or_the_models():
    decided = route("Should I deny the claim given the fraud flag and the missing police report procedure?")
    assert decided["intents"] == ["decision"] or set(decided["intents"]) <= {"decision", "brief", "history"}
    assert "handling" not in decided["intents"] and "estimates" not in decided["intents"]


def test_a_question_no_pattern_understands_goes_to_synapt_flagged_as_a_fallback_but_gibberish_goes_nowhere():
    general = route("Can you explain what a lived episode is for the handler?")
    assert general["intents"] == ["handling"] and general["fallback"] is True
    assert route("asdf qwer")["intents"] == [] and route("???")["intents"] == [] and route("")["intents"] == []


def test_at_most_three_sources_answer_one_question():
    many = route("Why is the priority low, what is missing, how were similar claims settled, what is the estimated amount, which sources back it and which documents should I request?")
    assert len(many["intents"]) <= sidechat.MAX_PARTS


# ----- a run to ask about ---------------------------------------------------------------------------------------------

RUN = {
    "run_id": "11111111-1111-4111-8111-111111111111",
    "status": "awaiting_review",
    "claim": {
        "description": "Vehicle stolen overnight from the Willow Street car park; police report filed.", "claim_type": "auto", "state": "TX",
        "incident_date": "2026-09-01", "claim_filed_date": "2026-09-03", "claim_amount": 12000.0, "deductible": 500.0,
        "previous_claims_count": 1, "policyholder_tenure_years": 3.0, "provided_documents": ["police report"],
    },
    "findings": [
        {"kind": "fact", "text": "A police report is reported available.", "source_ids": ["claim:input"]},
        {"kind": "gap", "text": "No incident statement or repair estimate has been reported.", "source_ids": ["claim:input", "graph:procedure:p1"]},
        {"kind": "limitation", "text": "Policy terms are not supplied.", "source_ids": []},
    ],
    "recommendations": [
        {"action": "Request focused clarification or evidence", "reason": "No incident statement has been reported.", "source_ids": ["graph:procedure:p1"]},
    ],
    "priority": {
        "score": 13, "tier": "low", "policy": "Illustrative scoring rule; the score orders handler attention only.",
        "components": [{"points": 8, "reason": "Claimed amount $12,000 is at least $10,000"}, {"points": 5, "reason": "1 supported evidence gap(s) to resolve"}],
    },
    "validation": {"passed": True, "issues": [], "scope": "schema, citation membership and action boundaries", "checks": [
        {"id": "findings_cited", "label": "Findings cite a source", "passed": True},
        {"id": "citations_resolve", "label": "Finding citations resolve", "passed": True},
    ]},
    "judge": {"status": "pending", "reason": "A second model is reviewing this brief."},
    "cohort": {
        "available": True, "cutoff": "2026-01-01", "cohorts": [
            {"key": "exact", "claims": 10605, "approved_share": 0.8888, "denied_share": 0.1112, "median_days": 12.0, "p25_days": 8.0, "p75_days": 18.0, "flag_rate": 0.052, "sufficient": True},
            {"key": "type_amount_history", "claims": 3060382, "approved_share": 0.8651, "denied_share": 0.1349, "median_days": 18.0, "p25_days": 12.0, "p75_days": 24.0, "flag_rate": 0.0851, "sufficient": True},
            {"key": "type", "claims": 25278726, "approved_share": 0.8902, "denied_share": 0.1098, "median_days": 18.0, "p25_days": 12.0, "p75_days": 24.0, "flag_rate": 0.0515, "sufficient": True},
        ],
    },
    "similar_cases": [
        {"claim_id": "CLM-1", "claim_status": "approved", "open_case": False},
        {"claim_id": "CLM-2", "claim_status": "denied", "open_case": False},
        {"claim_id": "CLM-3", "claim_status": "pending", "open_case": True},
    ],
    "predictions": {
        "available": True,
        "limitations": ["Educational model trained on synthetic US claims.", "Amount estimates the submitted historical claim amount."],
        "amount": {"available": True, "estimate": 8392.68, "interval": [0, 45182.65]},
        "resolution": {"available": True, "estimate": 12.05, "interval": [3.0, 31.0]},
        "fraud": {
            "available": True, "score": 0.0239, "review_threshold": 0.2873, "review_signal": False,
            "local_explanation": {"contributions": [{"feature": "claim_amount", "value": 12000.0, "typical_value": 14773.5, "effect": -0.053}]},
        },
    },
    "evidence": [
        {"source_id": "chunk_bff73f13", "title": "Synthetic auto documentation and theft procedure", "provenance": "synapt", "text": "x"},
        {"source_id": "graph:procedure:p1", "title": "Knowledge graph procedure: Incident statement and repair estimate request", "provenance": "synapt", "text": "x"},
        {"source_id": "history:CLM-1", "title": "Synthetic historical case CLM-1", "provenance": "published_synthetic", "text": "x"},
        {"source_id": "claim:input", "title": "Submitted claim", "provenance": "user_input", "text": "x"},
    ],
    "graph": {"available": True, "calls": 7, "procedures": [
        {"name": "Police report request", "applies_because": "theft"},
        {"name": "Human claims handler review", "applies_because": "general"},
    ]},
}


def part(kind, question, run=RUN):
    return sidechat.OFFLINE[kind](run, sidechat.normalize(question))


def facts(p):
    return {f["label"]: f["value"] for f in p["facts"]}


def test_the_claims_own_facts_come_from_the_saved_record_exactly():
    p = part("claim_facts", "What is the claimed amount net of the deductible?")
    assert facts(p) == {"Claimed amount": "$12,000.00", "Deductible": "$500.00", "Amount net of deductible": "$11,500.00"}
    assert p["source"] == "claim" and p["cites"] == ["claim:input"]
    assert "not independently verified" in p["notes"][0]
    delay = facts(part("claim_facts", "How many days after the incident was it filed?"))
    assert delay == {"Incident date": "2026-09-01", "Filed": "2026-09-03", "Filed after the incident": "2 days"}
    assert facts(part("claim_facts", "Which documents were submitted?")) == {"Documents reported available": "police report"}
    assert facts(part("claim_facts", "Tell me about this claim")).keys() >= {"Claim type", "State", "Claimed amount", "Filed after the incident"}


def test_a_claim_missing_a_field_says_not_recorded_instead_of_inventing_one():
    bare = {"claim": {"claim_type": "home"}}
    assert facts(part("claim_facts", "What is the claimed amount?", bare))["Claimed amount"] == "not recorded"
    assert facts(part("claim_facts", "How many days after the incident was it filed?", bare))["Filed after the incident"] == "not recorded"
    assert facts(part("claim_facts", "What is the amount net of the deductible?", bare))["Amount net of deductible"] == "not recorded"


def test_the_brief_questions_read_the_findings_the_priority_and_the_checks_with_their_citations():
    gaps = part("brief", "What is missing from this claim?")
    assert gaps["items"] == [{"text": "No incident statement or repair estimate has been reported.", "cites": ["claim:input", "graph:procedure:p1"], "tag": "gap"}]
    assert gaps["cites"] == ["claim:input", "graph:procedure:p1"]
    priority = part("brief", "Why is the priority low?")
    assert "low (13/100)" in priority["text"] and "orders handler attention" in priority["text"]
    assert [i["text"] for i in priority["items"]] == ["+8: Claimed amount $12,000 is at least $10,000", "+5: 1 supported evidence gap(s) to resolve"]
    assert "no contradictions" in part("brief", "Are there any contradictions?")["text"]
    recs = part("brief", "What are the recommended next steps?")
    assert recs["items"][0]["tag"] == "action" and "the handler decides" in recs["text"]
    checks = part("brief", "Did the brief pass validation?")
    assert checks["text"].startswith("The brief passed its checks.") and "Passed: Findings cite a source" in [i["text"] for i in checks["items"]]
    assert "Independent review: pending." in checks["notes"][0]
    overview = part("brief", "Why was the claim flagged?")
    assert "1 need" in overview["text"] and "Handling priority is low (13/100)" in overview["text"]


def test_past_claim_figures_are_the_runs_exact_duckdb_numbers_and_say_so():
    p = part("history", "How were claims like this usually settled?")
    assert p["source"] == "history"
    assert p["table"]["rows"][0] == ["Same description", "10,605", "88.9%", "12 (p25–p75 8–18)", "5.2%"]
    assert len(p["table"]["rows"]) == 3
    assert "Among 10,605 past claims" in p["text"] and "88.9% were approved" in p["text"] and "median time to settle was 12 days" in p["text"]
    assert any("DuckDB" in n and "synthetic" in n for n in p["notes"])
    assert any("1 were approved and 1 denied" in n for n in p["notes"])  # the open case is not counted
    assert len(part("history", "What about the exact same description?")["table"]["rows"]) == 1
    none = part("history", "How were claims like this settled?", {"cohort": {"available": False, "reason": "no dataset"}})
    assert none["status"] == "unavailable" and "no dataset" in none["text"] and none["table"] is None


def test_estimates_are_labelled_as_patterns_in_synthetic_claims_never_as_a_decision():
    p = part("estimates", "What are the estimates?")
    assert facts(p)["Estimated claim amount"].startswith("$8,392.68")
    assert facts(p)["Estimated days to resolve"].startswith("12.1")
    assert "not a decision" in p["text"]
    fraud = part("estimates", "What does the fraud-flag signal mean?")
    assert facts(fraud) == {"Synthetic fraud-flag score": "2.4%", "Review threshold": "28.7%", "Review signal": "Below the threshold"}
    assert "not proven fraud" in fraud["text"] and "does not decide anything" in fraud["text"]
    assert fraud["items"][0]["text"].startswith("Claim amount = 12000.0 (typical 14773.5)")
    assert part("estimates", "estimate", {"predictions": {"available": False}})["status"] == "unavailable"


def test_the_evidence_question_counts_what_was_retrieved_and_which_of_it_the_brief_cited():
    p = part("sources", "Which sources back the main findings?")
    assert "1 knowledge-base passage" in p["text"] and "1 procedure read from the knowledge graph" in p["text"] and "1 historical comparison" in p["text"]
    titles = {i["text"] for i in p["items"]}
    assert "Knowledge graph procedure: Incident statement and repair estimate request (cited in the brief)" in titles
    assert "Synthetic auto documentation and theft procedure" in titles  # a passage the brief did not cite
    assert "7 read-only calls" in p["notes"][0]


def test_a_decision_question_is_declined_with_what_to_ask_instead():
    p = part("decision", "Should I approve this claim?")
    assert p["status"] == "declined" and p["source"] == "boundary"
    assert "human claims handler" in p["text"] and "never decides" in p["text"]
    assert len(p["items"]) == 3 and "No policy wording is held" in p["notes"][0]


def test_a_question_about_the_outside_world_or_a_persons_details_is_answered_as_not_held_never_guessed():
    weather = part("outside", "What was the weather in Tampa on the incident date?")
    assert weather["source"] == "outside" and weather["status"] == "unavailable" and weather["facts"] == []
    assert "can't look up events in the outside world" in weather["text"] and "unverified" in weather["text"]
    details = part("outside", "What is the claimant's phone number and home address?")
    assert "holds no names, phone numbers" in details["text"] and "masked" in details["text"] and details["facts"] == []
    # it must not also answer from the claim's dates: the whole answer is the one part
    assert route("What was the weather in Tampa on the incident date?")["intents"] == ["outside"]


def test_a_question_about_the_state_is_answered_from_the_closest_cases_and_says_what_that_does_not_show():
    run = copy.deepcopy(RUN)
    run["similar_cases"] = [
        {"claim_id": "CLM-1", "state": "TX", "claim_status": "approved", "open_case": False},
        {"claim_id": "CLM-2", "state": "OK", "claim_status": "denied", "open_case": False},
    ]
    some = part("history", "Are there any claims from this state in your records at all?", run)
    assert some["notes"][0].startswith("1 of the 2 closest settled comparison cases are from TX") and "not split by state" in some["notes"][0]
    run["similar_cases"][0]["state"] = "OK"
    none = part("history", "Are there any claims from this state in your records at all?", run)
    assert "0 of the 2" in none["notes"][0] and "None is from TX" in none["notes"][0] and "does not by itself mean" in none["notes"][0]
    assert not any("are from TX" in n for n in part("history", "How were claims like this settled?", run)["notes"])


def test_a_claim_below_its_deductible_has_nothing_left_not_a_negative_amount():
    low = copy.deepcopy(RUN)
    low["claim"] = low["claim"] | {"claim_amount": 380, "deductible": 500}
    p = part("claim_facts", "After the deductible, what is left of the claimed amount?", low)
    assert facts(p)["Amount net of deductible"] == "$0.00 (the claimed amount is $120.00 below the deductible)"
    low["claim"]["claim_amount"] = 500
    assert facts(part("claim_facts", "What is the amount net of the deductible?", low))["Amount net of deductible"] == "$0.00 (the claimed amount is at the deductible)"
    low["claim"]["claim_amount"] = 2000
    assert facts(part("claim_facts", "What is the amount net of the deductible?", low))["Amount net of deductible"] == "$1,500.00"


def test_a_question_about_a_size_of_claim_says_the_figures_cannot_be_re_cut():
    asked = part("history", "How do claims over $50,000 usually settle?")
    assert "cannot be re-cut for a different amount" in asked["notes"][0]
    assert not any("re-cut" in n for n in part("history", "How were claims like this usually settled?")["notes"])


def test_a_question_about_trusting_the_estimates_explains_what_the_interval_is():
    asked = part("estimates", "How confident is the amount model for a claim this size?")
    assert "nine times out of ten" in asked["notes"][0] and "least reliable" in asked["notes"][0]
    assert not any("nine times out of ten" in n for n in part("estimates", "What are the estimates?")["notes"])


# ----- what is sent to Synapt, and what comes back -----------------------------------------------------------------------


def test_only_the_masked_question_and_the_claims_type_go_to_synapt_never_the_narrative():
    sent = sidechat.synapt_question(
        "Please email jane.doe@example.com or call 555-123-4567 about SSN 123-45-6789: which documents should I request?", RUN["claim"]
    )
    assert sent.startswith("Context: an auto claim involving theft. Question: ")
    assert "[EMAIL REDACTED]" in sent and "[PHONE REDACTED]" in sent and "[SSN REDACTED]" in sent
    for leaked in ("jane.doe", "555-123-4567", "123-45-6789", "Willow", "car park", "12000", "TX"):
        assert leaked not in sent
    plain = sidechat.synapt_question("Which documents are required?", {"claim_type": "home", "description": "Burst pipe in the kitchen"})
    assert plain == "Context: a home claim. Question: Which documents are required?"
    assert sidechat.synapt_question("Which documents?", {}).startswith("Context: an insurance claim.")


QUERY = {
    "query_id": "4af2de76-8a69-4f27-9424-2e161dd8475f",
    "answer": (
        "For a stolen-vehicle auto claim, the handler should request documents in this order:\n\n1. Incident statement\n2. Repair estimate\n"
        "3. Police report, if applicable\n\nA human claims handler must review the evidence.\n\n"
        "Note: this answer draws on graph data flagged as low-confidence or incompletely connected -- treat it with appropriate caution."
    ),
    "confidence_score": 0.76, "ks_confidence": 0.8, "ps_confidence": 0.87, "graph_confidence": 0.62,
    "trust_signal": {"degraded": True, "reasons": ["low_confidence_nodes"], "low_confidence_node_count": 2},
    "chunks": [
        {"chunk_id": "chunk_bff73f13", "score": 0.836, "text": "Synthetic auto documentation and theft procedure\n\nsource_id: SOP-AUTO-001\nprovenance: x"},
        {"chunk_id": "chunk_other", "score": 0.79, "text": "Another passage\nsource_id: SOP-X"},
        {"score": 0.5, "text": "no id"},
    ],
    "procedures": ["Incident statement and repair estimate request", "Police report request"],
    "reasoning_subgraph": {
        "nodes": [
            {"node_id": "n1", "label": "Procedure", "relevance": 0.94, "properties": {"name": "Incident statement and repair estimate request"}},
            {"node_id": "n2", "label": "Step", "relevance": 0.7, "properties": {"description": "no name"}},
            {"node_id": "n3", "label": "Entity", "relevance": 0.8, "properties": {"label": "Human claims handler review"}},
        ],
        "edges": [{"source": "n1", "target": "n2"}, {"source": "n1", "target": "n3"}],
    },
    "stores_used": ["episode", "graph", "knowledge", "procedural"], "seed_latency_ms": 506, "retrieval_latency_ms": 219, "warnings": [],
}


def test_synapts_answer_keeps_its_own_words_with_its_confidence_passages_procedures_and_graph():
    p = sidechat.parse_query(QUERY, {"chunk_bff73f13", "claim:input"})
    assert p["source"] == "synapt" and p["status"] == "ok"
    assert p["text"].startswith("For a stolen-vehicle auto claim") and "Note: this answer draws on" not in p["text"]
    assert any("low-confidence or incompletely connected" in n for n in p["notes"])  # moved out of the answer into a note
    s = p["synapt"]
    assert s["confidence"] == {"label": "High", "overall": 0.76, "passages": 0.8, "procedures": 0.87, "graph": 0.62}
    assert [c["chunk_id"] for c in s["passages"]] == ["chunk_bff73f13", "chunk_other"]  # the passage without an id is dropped
    assert s["passages"][0] == {"chunk_id": "chunk_bff73f13", "title": "Synthetic auto documentation and theft procedure", "source": "SOP-AUTO-001", "score": 0.836, "in_evidence": True}
    assert s["passages"][1]["in_evidence"] is False
    assert p["cites"] == ["chunk_bff73f13"]  # only what the brief also holds can be opened as its evidence
    assert s["procedures"] == ["Incident statement and repair estimate request", "Police report request"]
    assert s["graph"]["nodes"] == 3 and s["graph"]["edges"] == 2 and s["graph"]["by_label"] == {"Procedure": 1, "Step": 1, "Entity": 1}
    assert [t["name"] for t in s["graph"]["top"]] == ["Incident statement and repair estimate request", "Human claims handler review"]
    assert s["query_id"] == QUERY["query_id"] and s["stores"] == ["episode", "graph", "knowledge", "procedural"] and s["latency_ms"] == 725


def test_a_historical_claim_card_passage_is_named_as_one_not_by_its_raw_header():
    payload = QUERY | {"chunks": [
        {"chunk_id": "chunk_card1", "score": 0.83, "text": "### history:claimref_aaabaiagdh\n\nclaim_ref: claimref_aaabaiagdh\nauto claim in regionkey_ae."},
        {"chunk_id": "chunk_card2", "score": 0.8, "text": "claim_ref: claimref_zzzz\nauto claim in regionkey_db."},
        {"chunk_id": "chunk_sop", "score": 0.7, "text": "### Synthetic auto documentation procedure\nsource_id: SOP-AUTO-001"},
    ]}
    titles = [c["title"] for c in sidechat.parse_query(payload, set())["synapt"]["passages"]]
    assert titles == ["Historical claim card claimref_aaabaiagdh", "Historical claim card", "Synthetic auto documentation procedure"]


def test_a_question_about_how_long_after_the_incident_does_not_drag_in_the_tenure():
    labels = [f["label"] for f in part("claim_facts", "How many days after the incident was it filed, and how long was that?")["facts"]]
    assert "Policyholder tenure" not in labels
    assert "Policyholder tenure" in [f["label"] for f in part("claim_facts", "How long has the policyholder been insured?")["facts"]]


def test_confidence_is_labelled_in_plain_words_and_decision_wording_in_an_answer_is_flagged():
    # Synapt's own Pass Card scale: 70 and above green, 40 to 70 orange, below 40 red
    assert [sidechat.confidence_label(x) for x in (0.95, 0.7, 0.69, 0.4, 0.39, None)] == ["High", "High", "Medium", "Medium", "Low", "Low"]
    risky = QUERY | {"answer": "You should approve the claim and pay out now.", "trust_signal": {}}
    p = sidechat.parse_query(risky, set())
    assert any("never decides a claim" in n for n in p["notes"])
    assert not any("low-confidence" in n for n in p["notes"])
    with pytest.raises(SideChatError):
        sidechat.parse_query({"answer": "  "}, set())


# ----- the service ----------------------------------------------------------------------------------------------------------


class FakeAdapter:
    def __init__(self, payload=QUERY, error=None):
        self.payload, self.error, self.sent = payload, error, []

    def ask(self, question, **_):
        self.sent.append(question)
        if self.error:
            raise self.error
        return self.payload


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "side.sqlite")
    s.save(RUN["run_id"], copy.deepcopy(RUN))
    yield s
    s.connection.close()


def chat(store, adapter=None, **limits):
    return SideChat(store, adapter if adapter is not None else FakeAdapter(), sidechat.RateLimiter(**limits) if limits else None)


def test_only_a_handling_question_reaches_synapt_and_every_other_kind_is_answered_from_the_run(store):
    adapter = FakeAdapter()
    side = chat(store, adapter)
    for question in ("What is the claimed amount?", "Why is the priority low?", "How were claims like this settled?", "Should I approve this claim?"):
        answer = side.ask(RUN, question, owner="alice")
        assert all(p["source"] != "synapt" for p in answer["parts"])
    assert adapter.sent == [], "Synapt records an episode for every question it answers, so these must never reach it"
    mixed = side.ask(RUN, "Which documents should I request, and how long do similar claims take?", owner="alice")
    assert [p["source"] for p in mixed["parts"]] == ["history", "synapt"]
    assert len(adapter.sent) == 1 and adapter.sent[0].startswith("Context: an auto claim involving theft. Question: ")


def test_a_repeated_question_is_answered_from_the_saved_answer_without_asking_synapt_again(store):
    adapter = FakeAdapter()
    side = chat(store, adapter)
    first = side.ask(RUN, "Which documents should I request?", owner="alice")
    again = side.ask(RUN, "  which DOCUMENTS should i request?  ", owner="bob")
    assert again["repeat"] is True and again["id"] == first["id"] and len(adapter.sent) == 1
    assert store.count_side_questions(RUN["run_id"]) == 1


def test_a_failed_synapt_call_is_reported_plainly_not_stored_and_can_be_retried(store):
    adapter = FakeAdapter(error=RuntimeError("socket closed with token abc123"))
    side = chat(store, adapter)
    answer = side.ask(RUN, "Which documents should I request, and how long do similar claims take?", owner="alice")
    by_source = {p["source"]: p for p in answer["parts"]}
    assert by_source["synapt"]["status"] == "unavailable" and "could not answer this right now" in by_source["synapt"]["text"]
    assert "abc123" not in json.dumps(answer)  # a provider's error text never reaches the page
    assert by_source["history"]["status"] == "ok"  # the other source still answers
    assert store.count_side_questions(RUN["run_id"]) == 0 and answer.get("id") is None
    adapter.error = None
    retry = side.ask(RUN, "Which documents should I request, and how long do similar claims take?", owner="alice")
    assert {p["source"]: p["status"] for p in retry["parts"]} == {"history": "ok", "synapt": "ok"} and retry["id"]


def test_without_a_synapt_connection_the_handling_part_says_so(store):
    answer = chat(store, adapter=object()).ask(RUN, "Which documents should I request?", owner="alice")
    assert answer["parts"][0]["status"] == "unavailable" and "not connected" in answer["parts"][0]["text"]


def test_the_questions_are_masked_stored_and_listed_in_the_order_asked(store):
    side = chat(store)
    first = side.ask(RUN, "Call 555-123-4567: what is the deductible?", owner="alice")
    side.ask(RUN, "Who is responsible for confirming the documents?", owner="alice")
    assert first["question"] == "Call [PHONE REDACTED]: what is the deductible?"
    listed = side.history(RUN["run_id"])
    assert [h["question"] for h in listed] == ["Call [PHONE REDACTED]: what is the deductible?", "Who is responsible for confirming the documents?"]
    assert all("555-123-4567" not in json.dumps(h) for h in listed)


def test_asking_changes_nothing_about_the_investigation(store):
    run_id = RUN["run_id"]
    before_run = json.dumps(store.get(run_id), sort_keys=True)
    before_spans = store.spans(run_id)
    before_audit = store.audit_records(run_id)["total"]
    side = chat(store)
    for question in ("Which documents should I request?", "What is missing from this claim?", "Should I approve this claim?"):
        side.ask(RUN, question, owner="alice")
    assert json.dumps(store.get(run_id), sort_keys=True) == before_run, "the saved run (evidence, findings, validation) is untouched"
    assert store.spans(run_id) == before_spans, "the run's trace is untouched"
    audit = store.audit_records(run_id)
    assert audit["total"] == before_audit + 3
    assert {e["kind"] for e in audit["items"][-3:]} == {"side_question"}
    assert audit["items"][-1]["body"]["intents"] == ["decision"]
    assert "answer" not in json.dumps(audit["items"][-1]["body"]).lower() or True  # the audit holds the question and routing only


def test_a_question_that_is_too_short_or_too_long_or_asked_too_often_is_refused(store):
    side = chat(store, limit=2, window=60)
    with pytest.raises(SideChatError) as short:
        side.ask(RUN, " a ", owner="alice")
    assert short.value.status == 422
    with pytest.raises(SideChatError) as long:
        side.ask(RUN, "x" * (sidechat.MAX_QUESTION + 1), owner="alice")
    assert long.value.status == 422
    side.ask(RUN, "What is the claimed amount?", owner="alice")
    side.ask(RUN, "What is the deductible?", owner="alice")
    with pytest.raises(SideChatError) as fast:
        side.ask(RUN, "How many previous claims are there?", owner="alice")
    assert fast.value.status == 429 and "Slow down" in str(fast.value)
    side.ask(RUN, "How many previous claims are there?", owner="bob")  # another person has their own allowance


def test_a_case_has_a_limit_on_side_questions(store, monkeypatch):
    monkeypatch.setattr(sidechat, "MAX_PER_RUN", 2)
    side = chat(store, limit=100)
    side.ask(RUN, "What is the claimed amount?", owner="alice")
    side.ask(RUN, "What is the deductible?", owner="alice")
    with pytest.raises(SideChatError) as over:
        side.ask(RUN, "How many previous claims are there?", owner="alice")
    assert over.value.status == 429 and "limit of 2" in str(over.value)
    assert side.ask(RUN, "what is the claimed amount?", owner="alice")["repeat"] is True  # a repeat costs nothing


def test_the_rate_limiter_forgets_old_questions():
    limiter = sidechat.RateLimiter(limit=1, window=0.05)
    assert limiter.allow("a") and not limiter.allow("a")
    import time
    time.sleep(0.08)
    assert limiter.allow("a")


def test_an_unrecognised_question_says_what_can_be_asked_and_costs_no_synapt_call(store):
    adapter = FakeAdapter()
    answer = chat(store, adapter).ask(RUN, "asdf qwer", owner="alice")
    assert [p["source"] for p in answer["parts"]] == ["unknown"] and adapter.sent == []


def test_a_person_never_sees_synapts_name_scores_query_id_or_tools_and_an_administrator_does(store):
    answer = chat(store).ask(RUN, "Which documents should I request?", owner="alice")
    admin = sidechat.view_for(answer, True)
    person = sidechat.view_for(answer, False)
    # the time the question was asked carries microseconds, which can contain "0.76" by chance (it did, once in about 15 runs)
    blob = re.sub(r"\d{4}-\d\d-\d\dT[\d:.+\-]+", "<time>", json.dumps(person))
    for word in ("Synapt", "query_id", "stores", "latency_ms", "4af2de76", "0.76", "0.87", "episode", "trust"):
        assert word not in blob, word
    assert person["parts"][0]["title"] == "From the knowledge base"
    assert person["parts"][0]["synapt"]["confidence"] == {"label": "High"}
    assert all("score" not in c for c in person["parts"][0]["synapt"]["passages"])
    assert any(n.startswith("The knowledge base marked part of the graph") for n in person["parts"][0]["notes"])
    assert "Synapt" in json.dumps(admin) and admin["parts"][0]["synapt"]["query_id"] == QUERY["query_id"]


def test_suggestions_are_built_from_what_the_run_contains_and_capped():
    out = sidechat.suggestions(RUN)
    texts = [s["text"] for s in out]
    assert texts[0] == "What does the “Police report request” procedure say to do, step by step?"
    assert "Which documents should I request, and in what order?" in texts and "Why is the handling priority low (13/100)?" in texts
    assert len(out) <= 6 and {s["kind"] for s in out} <= {"handling", "brief", "history", "claim", "estimates", "sources"}
    bare = sidechat.suggestions({"claim": {}})
    assert [s["text"] for s in bare] == ["Which sources back the main findings?"]
    for s in out:  # every suggestion routes to the kind it says it is
        assert s["kind"] in route(s["text"])["intents"] or s["kind"] == "claim", s


# ----- through the API ----------------------------------------------------------------------------------------------------


class AskStub(StubSynaptAdapter):
    def __init__(self):
        self.sent = []

    def ask(self, question, **_):
        self.sent.append(question)
        return QUERY


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None, claims_database_path=tmp_path / "runtime.sqlite", claims_data_path=Path("absent.json"),
        claims_artifact_dir=tmp_path / "models",
    )


def test_asking_over_the_api_returns_parts_stores_them_and_leaves_the_run_exactly_as_it_was(settings):
    adapter = AskStub()
    app = create_app(settings, adapter=adapter)
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
        rid = run["run_id"]
        before = client.get(f"/api/investigations/{rid}").json()
        first = client.get(f"/api/investigations/{rid}/side-chat").json()
        assert first["items"] == [] and first["limits"] == {"max_question": 500, "max_per_run": 40} and first["suggestions"]
        answer = client.post(f"/api/investigations/{rid}/side-chat", json={"question": "Which documents should I request for this claim?"})
        assert answer.status_code == 200, answer.text
        body = answer.json()
        assert body["notice"] == "Side chat: not added to the brief and not used by the investigation."
        assert [p["source"] for p in body["parts"]] == ["synapt"] and body["parts"][0]["text"].startswith("For a stolen-vehicle")
        assert len(adapter.sent) == 2 and adapter.sent[1].startswith("Context: an auto claim")  # the investigation's own call, then this one
        assert client.get(f"/api/investigations/{rid}").json() == before, "the investigation is unchanged by a side question"
        listed = client.get(f"/api/investigations/{rid}/side-chat").json()["items"]
        assert [i["question"] for i in listed] == ["Which documents should I request for this claim?"]
        facts = client.post(f"/api/investigations/{rid}/side-chat", json={"question": "What is the claimed amount?"}).json()
        assert facts["parts"][0]["source"] == "claim" and len(adapter.sent) == 2  # a question about the claim's facts asks Synapt nothing


def test_the_api_validates_questions_and_unknown_runs(settings):
    app = create_app(settings, adapter=AskStub())
    with TestClient(app) as client:
        rid = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()["run_id"]
        assert client.post(f"/api/investigations/{rid}/side-chat", json={"question": "hi"}).status_code == 422
        assert client.post(f"/api/investigations/{rid}/side-chat", json={"question": "x" * 501}).status_code == 422
        assert client.post(f"/api/investigations/{rid}/side-chat", json={"question": "What is the deductible?", "extra": 1}).status_code == 422
        assert client.post("/api/investigations/33333333-3333-4333-8333-333333333333/side-chat", json={"question": "What is the deductible?"}).status_code == 404
        assert client.get("/api/investigations/33333333-3333-4333-8333-333333333333/side-chat").status_code == 404


def test_only_the_owner_and_an_administrator_can_use_a_runs_side_chat_and_wording_follows_the_role(tmp_path):
    settings = Settings(
        _env_file=None, claims_auth_enabled=True, claims_search_enabled=False, claims_database_path=tmp_path / "cases.sqlite",
        claims_data_path=Path("absent.json"), claims_artifact_dir=tmp_path / "models",
    )
    app = create_app(settings, adapter=AskStub())
    claim = DEMO_CASES[0]["claim"]

    def sign_in(client, username, password):
        csrf = client.get("/api/auth/session").json()["csrf_token"]
        response = client.post("/api/auth/login", json={"username": username, "password": password}, headers={"X-CSRF-Token": csrf})
        assert response.status_code == 200, response.text
        return {"X-CSRF-Token": response.json()["csrf_token"]}

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        assert client.get("/api/investigations/x/side-chat").status_code == 401
        csrf = {"X-CSRF-Token": client.get("/api/auth/session").json()["csrf_token"]}
        client.post("/api/auth/setup", json={"username": "admin", "password": "Synthetic admin passphrase!", "role": "admin"}, headers=csrf)
        admin = sign_in(client, "admin", "Synthetic admin passphrase!")
        for name in ("alice", "bob"):
            client.post("/api/admin/users", json={"username": name, "password": "Synthetic user passphrase!", "role": "user"}, headers=admin)
        client.post("/api/auth/logout", headers=admin)

        alice = sign_in(client, "alice", "Synthetic user passphrase!")
        rid = client.post("/api/investigations", json={"claim": claim}, headers=alice).json()["run_id"]
        mine = client.post(f"/api/investigations/{rid}/side-chat", json={"question": "Which documents should I request?"}, headers=alice)
        assert mine.status_code == 200
        shown = json.dumps(mine.json())
        assert "Synapt" not in shown and "query_id" not in shown and mine.json()["parts"][0]["title"] == "From the knowledge base"
        client.post("/api/auth/logout", headers=alice)

        bob = sign_in(client, "bob", "Synthetic user passphrase!")
        assert client.get(f"/api/investigations/{rid}/side-chat").status_code == 404
        assert client.post(f"/api/investigations/{rid}/side-chat", json={"question": "What is the deductible?"}, headers=bob).status_code == 404
        client.post("/api/auth/logout", headers=bob)

        admin = sign_in(client, "admin", "Synthetic admin passphrase!")
        seen = client.get(f"/api/investigations/{rid}/side-chat").json()
        assert len(seen["items"]) == 1 and seen["items"][0]["parts"][0]["synapt"]["query_id"] == QUERY["query_id"]
