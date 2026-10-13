"""Retrieval metrics for the two things the investigation reads from Synapt: procedures (SOPs) and similar past claims (tickets).

The golden suite and the judges score the finished brief. Nothing there says whether retrieval found the right material in the
first place, so a weak retrieval leg could hide behind a model that writes well. This module measures retrieval on its own,
with standard information-retrieval metrics:

* precision@k: share of the top k results that are relevant;
* recall@k: share of the needed items that appear in the top k (for procedures, RAGAS calls this context recall);
* hit@k: whether any needed item appears in the top k;
* MRR: 1 / rank of the first needed item (0 when none is returned);
* nDCG@k: graded ranking quality, gain 2^grade - 1, normalised by the ideal ordering.

Ground truth never comes from the rules the application uses to pick results (``knowledge_graph.applies``): grading the system
with its own rule would score it against itself. Procedures are graded from the hand-labelled query set below. Tickets are
graded from the workbook that was uploaded to Synapt, using columns the ticket store also stores.
"""

import math
import re
from collections.abc import Iterable, Sequence

from claims.corpus.cards import amount_band, delay_band, history_band, tenure_band

K = 5

# ---- metric functions ---------------------------------------------------------------------------------------------------


def precision_at_k(ranked: Sequence, relevant: set, k: int = K) -> float:
    """Relevant results in the top k, divided by k (missing results count as not relevant)."""
    return sum(item in relevant for item in ranked[:k]) / k


def recall_at_k(ranked: Sequence, needed: set, k: int | None = K) -> float | None:
    """Share of ``needed`` found in the top k (all results when k is None). None when nothing is needed."""
    if not needed:
        return None
    return len(needed & set(ranked if k is None else ranked[:k])) / len(needed)


def hit_at_k(ranked: Sequence, needed: set, k: int = K) -> float:
    return float(any(item in needed for item in ranked[:k]))


def reciprocal_rank(ranked: Sequence, needed: set) -> float:
    return next((1 / rank for rank, item in enumerate(ranked, 1) if item in needed), 0.0)


def ndcg_at_k(grades: Sequence[float], ideal: Iterable[float], k: int = K) -> float | None:
    """nDCG of the returned grades against the best possible ordering of every gradeable item. None when nothing has a grade."""

    def dcg(values):
        return sum((2**g - 1) / math.log2(rank + 1) for rank, g in enumerate(values[:k], 1))

    best = dcg(sorted(ideal, reverse=True))
    return None if best == 0 else dcg(list(grades)) / best


def mean(values: Iterable[float | None]) -> float | None:
    kept = [v for v in values if v is not None]
    return round(sum(kept) / len(kept), 4) if kept else None


def dedupe(items: Iterable) -> list:
    """Document-level ranking: each item once, at its first (best) rank. Several chunks or graph procedures can come from one SOP."""
    return list(dict.fromkeys(items))


# ---- procedures (SOP documents) -----------------------------------------------------------------------------------------

SOP_ID = re.compile(r"\bsource_id:\s*(SOP-[A-Z]+(?:-[A-Z]+)*-\d{3})\b")

# Handling procedures that fit any claim. They are relevant (grade 1) but never "needed": a claim-specific procedure is.
# FRAUD-SIGNAL-001 applies when the fraud review signal is high, which is only known after retrieval, so retrieving it is not
# penalised and not required.
GENERAL_SOPS = frozenset({
    "SOP-REVIEW-001", "SOP-CONFLICT-001", "SOP-OUTSTANDING-001", "SOP-PRIVACY-001", "SOP-FRAUD-SIGNAL-001",
})
ALL_SOPS = frozenset({
    "SOP-AUTO-001", "SOP-BUSINESS-001", "SOP-COLLISION-001", "SOP-CONFLICT-001", "SOP-DOWNTIME-001", "SOP-FRAUD-SIGNAL-001",
    "SOP-INVENTORY-001", "SOP-LARGE-LOSS-001", "SOP-LATE-FILING-001", "SOP-NEW-POLICY-001", "SOP-OUTSTANDING-001",
    "SOP-PRIVACY-001", "SOP-PROPERTY-001", "SOP-REPEAT-CLAIMANT-001", "SOP-REVIEW-001", "SOP-THEFT-001", "SOP-WATER-001",
})


def sop_in_text(text: str) -> str | None:
    """The SOP a passage belongs to, from the ``source_id:`` header every procedure document carries."""
    match = SOP_ID.search(text or "")
    return match.group(1) if match else None


def sop_grade(sop: str | None, needs: frozenset) -> int:
    """2: this claim needs the procedure; 1: general handling that fits any claim; 0: another claim's procedure, or unknown."""
    return 2 if sop in needs else 1 if sop in GENERAL_SOPS else 0


def score_sops(ranked_sops: Sequence[str | None], needs: frozenset, k: int = K) -> dict:
    """Metrics for one claim's document-level SOP ranking (None = a result that maps to no known SOP)."""
    relevant = needs | GENERAL_SOPS
    grades = [sop_grade(s, needs) for s in ranked_sops]
    return {
        "retrieved": list(ranked_sops),
        "needed": sorted(needs),
        "missed": sorted(needs - set(ranked_sops)),
        "off_target": [s for s in ranked_sops if sop_grade(s, needs) == 0],
        f"precision@{k}": round(precision_at_k(ranked_sops, relevant, k), 4),
        "precision": round(sum(g > 0 for g in grades) / len(grades), 4) if grades else 0.0,
        f"recall@{k}": recall_at_k(ranked_sops, needs, k),
        "recall": recall_at_k(ranked_sops, needs, None),
        f"hit@{k}": hit_at_k(ranked_sops, needs, k),
        "mrr": reciprocal_rank(ranked_sops, needs),
        f"ndcg@{k}": ndcg_at_k(grades, [2] * len(needs) + [1] * len(GENERAL_SOPS), k),
    }


def _claim(description, claim_type, state, incident, filed, amount, previous, tenure, documents=()):
    return {
        "description": description,
        "claim_type": claim_type,
        "state": state,
        "incident_date": incident,
        "claim_filed_date": filed,
        "claim_amount": amount,
        "deductible": 500 if amount < 20_000 else 1_000,
        "previous_claims_count": previous,
        "policyholder_tenure_years": tenure,
        "provided_documents": list(documents),
    }


# Hand-labelled retrieval queries: each claim and the procedures a handler would need for it, read from each SOP's "applies
# when" sentence (src/claims/corpus/builder.py SOPS and src/claims/corpus/procedures.py). The thresholds behind the condition
# procedures: filed more than 30 days after the incident, $50,000 or more, three or more earlier claims, a policy under a year.
# Every claim type and every condition procedure is covered at least twice. The first three are the golden cases.
RETRIEVAL_QUERIES: tuple[dict, ...] = (
    {"id": "auto-ready", "needs": {"SOP-AUTO-001", "SOP-COLLISION-001"},
     "claim": _claim("My car was rear-ended at a junction. A repair estimate is available.", "auto", "TX",
                     "2026-09-01", "2026-09-02", 8500, 0, 4, ("incident statement", "repair estimate"))},
    {"id": "theft-gap", "needs": {"SOP-AUTO-001", "SOP-THEFT-001", "SOP-REPEAT-CLAIMANT-001", "SOP-NEW-POLICY-001"},
     "claim": _claim("My car was stolen from the parking area. I have not supplied a police report.", "auto", "CA",
                     "2026-08-01", "2026-08-18", 42000, 3, 0.5, ("incident statement",))},
    {"id": "home-conflict", "needs": {"SOP-PROPERTY-001", "SOP-WATER-001", "SOP-LARGE-LOSS-001"},
     "claim": _claim("My home has water damage. A burst pipe caused it; another statement says there was no burst pipe.",
                     "home", "FL", "2026-09-04", "2026-09-06", 67000, 1, 7, ("incident statement",))},
    {"id": "auto-scrape-repeat", "needs": {"SOP-AUTO-001", "SOP-COLLISION-001", "SOP-REPEAT-CLAIMANT-001"},
     "claim": _claim("Another car scraped the side of my parked vehicle in a car park and drove off.", "auto", "OH",
                     "2026-07-10", "2026-07-12", 3200, 5, 9)},
    {"id": "auto-theft-late-large", "needs": {"SOP-AUTO-001", "SOP-THEFT-001", "SOP-LATE-FILING-001", "SOP-LARGE-LOSS-001"},
     "claim": _claim("My pickup truck was stolen overnight from outside my house while I was travelling.", "auto", "GA",
                     "2026-05-02", "2026-06-20", 61000, 0, 6)},
    {"id": "auto-hail-new-policy", "needs": {"SOP-AUTO-001", "SOP-COLLISION-001", "SOP-NEW-POLICY-001"},
     "claim": _claim("Hail dented the roof and bonnet of my car during a storm.", "auto", "CO",
                     "2026-06-03", "2026-06-05", 4800, 0, 0.4)},
    {"id": "home-leak", "needs": {"SOP-PROPERTY-001", "SOP-WATER-001"},
     "claim": _claim("A leak under the kitchen sink soaked the cabinets and floor.", "home", "WA",
                     "2026-08-11", "2026-08-13", 6200, 0, 5)},
    {"id": "home-fire-large", "needs": {"SOP-PROPERTY-001", "SOP-LARGE-LOSS-001"},
     "claim": _claim("A kitchen fire damaged the kitchen and smoke spread through the ground floor.", "home", "AZ",
                     "2026-07-21", "2026-07-23", 85000, 1, 12)},
    {"id": "property-storm-late", "needs": {"SOP-PROPERTY-001", "SOP-LATE-FILING-001"},
     "claim": _claim("A storm tore shingles off the roof of the rental property I own.", "property", "NC",
                     "2026-03-01", "2026-04-15", 14000, 1, 8)},
    {"id": "property-pipe-repeat", "needs": {"SOP-PROPERTY-001", "SOP-WATER-001", "SOP-REPEAT-CLAIMANT-001"},
     "claim": _claim("A frozen pipe burst in the basement of the property and flooded the storage room.", "property", "MN",
                     "2026-01-14", "2026-01-16", 22000, 4, 10)},
    {"id": "renters-burglary", "needs": {"SOP-PROPERTY-001", "SOP-INVENTORY-001"},
     "claim": _claim("Someone broke into my apartment and took my laptop, a television and jewellery.", "renters", "IL",
                     "2026-08-20", "2026-08-21", 5400, 0, 2)},
    {"id": "renters-leak-new-policy", "needs": {"SOP-PROPERTY-001", "SOP-INVENTORY-001", "SOP-NEW-POLICY-001"},
     "claim": _claim("Water leaking from the flat upstairs ruined my sofa, rug and clothes.", "renters", "NY",
                     "2026-09-02", "2026-09-04", 3800, 0, 0.3)},
    {"id": "business-flood-large", "needs": {"SOP-BUSINESS-001", "SOP-DOWNTIME-001", "SOP-LARGE-LOSS-001"},
     "claim": _claim("Our warehouse flooded, the stock on the floor was lost and we closed for two weeks.", "business", "LA",
                     "2026-06-10", "2026-06-14", 120000, 1, 6)},
    {"id": "business-equipment", "needs": {"SOP-BUSINESS-001"},
     "claim": _claim("Two laptops and a projector were damaged when the office ceiling collapsed.", "business", "PA",
                     "2026-07-01", "2026-07-03", 9500, 0, 4)},
    {"id": "business-fire-late-repeat",
     "needs": {"SOP-BUSINESS-001", "SOP-DOWNTIME-001", "SOP-LATE-FILING-001", "SOP-REPEAT-CLAIMANT-001"},
     "claim": _claim("A fire in the restaurant kitchen forced us to close for a month and we lost the income.", "business",
                     "NV", "2026-04-01", "2026-05-12", 38000, 3, 5)},
)


# ---- similar past claims (tickets) --------------------------------------------------------------------------------------

TICKET_ATTRIBUTES = ("category", "amount", "delay", "tenure", "history")


def ticket_profile(category, amount, delay_days, tenure_years, previous_claims) -> dict:
    """The banded attributes a ticket's embedded description is written from (claims.corpus.cards.claim_card_text)."""
    return {
        "category": category or "",
        "amount": amount_band(float(amount)),
        "delay": delay_band(int(delay_days)),
        "tenure": tenure_band(float(tenure_years)),
        "history": history_band(int(previous_claims)),
    }


def workbook_profile(row: dict) -> dict:
    return ticket_profile(row["category"], row["claim_amount_usd"], row["days_from_incident_to_filing"],
                          row["policyholder_tenure_years"], row["previous_claims"])


def claim_profile(claim: dict) -> dict:
    from datetime import date

    delay = (date.fromisoformat(str(claim["claim_filed_date"])[:10]) - date.fromisoformat(str(claim["incident_date"])[:10])).days
    return ticket_profile(claim.get("claim_type"), claim["claim_amount"], delay, claim["policyholder_tenure_years"],
                          claim["previous_claims_count"])


def agreement(query: dict, neighbour: dict) -> int:
    """How many of the five banded attributes a neighbour shares with the query (0-5): the graded relevance for nDCG."""
    return sum(query[a] == neighbour[a] for a in TICKET_ATTRIBUTES)


def score_neighbours(query: dict, neighbours: Sequence[dict | None], k: int) -> dict:
    """One query's returned past claims (profiles, None when a returned ID is not in the workbook).

    Relevant means the same claim type: a past claim of another type is not a comparable case. nDCG uses the attribute
    agreement as the grade (scaled to 0-2 so it is on the same footing as the procedure grades) against an ideal list of
    k perfectly matching tickets."""
    same = [n is not None and n["category"] == query["category"] for n in neighbours]
    agreements = [0 if n is None else agreement(query, n) for n in neighbours]
    grades = [2 * a / len(TICKET_ATTRIBUTES) for a in agreements]
    return {
        "k": k,
        "returned": len(neighbours),
        "unknown_ids": sum(n is None for n in neighbours),
        "precision_at_k": round(sum(same[:k]) / k, 4),
        "same_type_share": round(sum(same) / len(same), 4) if same else None,
        "mean_agreement": round(sum(agreements) / len(agreements), 3) if agreements else None,
        "ndcg": ndcg_at_k(grades, [2.0] * k, k),
    }


def score_known_item(own: str, ranked: Sequence[str]) -> dict:
    """A ticket that is in the store, sent as the query: is it its own nearest neighbour? Recall for a single known item."""
    return {"hit@1": float(list(ranked[:1]) == [own]), "found": own in ranked, "rr": reciprocal_rank(ranked, {own})}
