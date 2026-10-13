import math
from datetime import date

import pytest

from claims.core.schemas import ClaimInput
from claims.corpus.builder import SOPS
from claims.corpus.procedures import PROCEDURES
from claims.evaluation import retrieval as rm
from claims.synapt import knowledge_graph
from claims.synapt.adapter import ticket_examples


def test_precision_divides_by_k_so_empty_slots_count_against_a_short_list():
    assert rm.precision_at_k(["a", "b"], {"a"}, k=4) == 0.25
    assert rm.precision_at_k(["a", "b", "c", "d", "e"], {"a", "c"}, k=5) == 0.4


def test_recall_hit_and_reciprocal_rank():
    ranked = ["x", "a", "y", "b"]
    assert rm.recall_at_k(ranked, {"a", "b", "c"}, k=2) == pytest.approx(1 / 3)
    assert rm.recall_at_k(ranked, {"a", "b", "c"}, k=None) == pytest.approx(2 / 3)
    assert rm.recall_at_k(ranked, set(), k=2) is None
    assert rm.hit_at_k(ranked, {"b"}, k=3) == 0.0 and rm.hit_at_k(ranked, {"b"}, k=4) == 1.0
    assert rm.reciprocal_rank(ranked, {"a", "b"}) == 0.5
    assert rm.reciprocal_rank(ranked, {"z"}) == 0.0


def test_ndcg_is_one_for_the_ideal_order_and_lower_when_it_is_reversed():
    assert rm.ndcg_at_k([2, 1, 0], [2, 1], k=3) == pytest.approx(1.0)
    reversed_order = rm.ndcg_at_k([0, 1, 2], [2, 1], k=3)
    expected = (1 / math.log2(3) + 3 / math.log2(4)) / (3 + 1 / math.log2(3))
    assert reversed_order == pytest.approx(expected)
    assert rm.ndcg_at_k([0, 0], [], k=2) is None


def test_dedupe_keeps_each_document_at_its_best_rank():
    assert rm.dedupe(["SOP-A", None, "SOP-A", "SOP-B", None]) == ["SOP-A", None, "SOP-B"]


def test_sop_scoring_grades_needed_general_and_off_target_documents():
    needs = frozenset({"SOP-AUTO-001", "SOP-THEFT-001"})
    score = rm.score_sops(["SOP-COLLISION-001", "SOP-AUTO-001", "SOP-REVIEW-001", None], needs)
    assert score["missed"] == ["SOP-THEFT-001"]
    assert score["off_target"] == ["SOP-COLLISION-001", None]
    assert score["precision@5"] == pytest.approx(2 / 5)
    assert score["precision"] == pytest.approx(2 / 4)
    assert score["recall"] == 0.5 and score["mrr"] == 0.5 and score["hit@5"] == 1.0


def test_the_source_id_header_identifies_a_procedure_passage():
    assert rm.sop_in_text("Synthetic x\n\nsource_id: SOP-REPEAT-CLAIMANT-001\nprovenance: y") == "SOP-REPEAT-CLAIMANT-001"
    assert rm.sop_in_text("no header here") is None


def test_every_known_procedure_is_in_the_grading_universe():
    authored = {sop for sop, _, _ in SOPS} | {p[0] for p in PROCEDURES}
    assert authored == rm.ALL_SOPS
    assert rm.GENERAL_SOPS <= rm.ALL_SOPS


@pytest.mark.parametrize("query", rm.RETRIEVAL_QUERIES, ids=lambda q: q["id"])
def test_each_labelled_query_is_a_valid_claim_whose_needs_agree_with_its_own_fields(query):
    claim = ClaimInput.model_validate(query["claim"])
    needs = query["needs"]
    assert needs <= rm.ALL_SOPS and not needs & rm.GENERAL_SOPS
    # The structured conditions are labelled exactly when the claim meets the threshold the procedure states.
    cues = set(knowledge_graph.active_cues(claim))
    for cue, sop in {
        "late_filing": "SOP-LATE-FILING-001",
        "large_loss": "SOP-LARGE-LOSS-001",
        "repeat_claimant": "SOP-REPEAT-CLAIMANT-001",
        "new_policyholder": "SOP-NEW-POLICY-001",
    }.items():
        assert (cue in cues) == (sop in needs), (cue, sop)
    kind = claim.claim_type.value
    type_sop = {"auto": "SOP-AUTO-001", "business": "SOP-BUSINESS-001"}.get(kind, "SOP-PROPERTY-001")
    assert type_sop in needs


def test_the_query_set_covers_every_claim_type_and_every_specific_procedure_twice():
    kinds = {q["claim"]["claim_type"] for q in rm.RETRIEVAL_QUERIES}
    assert kinds == {"auto", "business", "home", "property", "renters"}
    for sop in rm.ALL_SOPS - rm.GENERAL_SOPS:
        assert sum(sop in q["needs"] for q in rm.RETRIEVAL_QUERIES) >= 2, sop


def test_ticket_neighbours_are_relevant_when_the_claim_type_matches():
    query = rm.ticket_profile("auto", 8000, 2, 4, 0)
    same = rm.ticket_profile("auto", 9000, 2, 4, 0)
    other = rm.ticket_profile("home", 8000, 2, 4, 0)
    assert rm.agreement(query, same) == 5 and rm.agreement(query, other) == 4
    score = rm.score_neighbours(query, [same, other, None], k=3)
    assert score["precision_at_k"] == pytest.approx(1 / 3, abs=1e-4)
    assert score["same_type_share"] == pytest.approx(1 / 3, abs=1e-4)
    assert score["unknown_ids"] == 1
    assert score["mean_agreement"] == 3.0
    assert 0 < score["ndcg"] < 1


def test_claim_and_workbook_profiles_use_the_same_bands():
    claim = {"claim_type": "home", "incident_date": date(2026, 1, 1).isoformat(), "claim_filed_date": "2026-01-03",
             "claim_amount": 6200, "policyholder_tenure_years": 5, "previous_claims_count": 0}
    row = {"category": "home", "claim_amount_usd": 6200.0, "days_from_incident_to_filing": 2.0,
           "policyholder_tenure_years": 5.0, "previous_claims": 0.0}
    assert rm.claim_profile(claim) == rm.workbook_profile(row)


def test_known_item_scores_the_ticket_against_itself():
    assert rm.score_known_item("claimref_abcd", ["claimref_abcd", "claimref_bcde"]) == {"hit@1": 1.0, "found": True, "rr": 1.0}
    assert rm.score_known_item("claimref_abcd", ["claimref_bcde", "claimref_abcd"])["rr"] == 0.5
    assert rm.score_known_item("claimref_abcd", [])["found"] is False


def test_ticket_examples_rank_aliases_by_score_once_each():
    item = {"fields": {
        "resolution": {"labels": [{"example": {"ticket_id": "claimref_bbbb", "score": 0.8}},
                                  {"example": {"ticket_id": "claimref_aaaa", "score": 0.9}}]},
        "fraud_flag": {"labels": [{"example": {"ticket_id": "claimref_aaaa", "score": 0.9}},
                                  {"example": {"ticket_id": "not-an-alias", "score": 1.0}}]},
    }}
    assert ticket_examples(item) == ["claimref_aaaa", "claimref_bbbb"]
