"""Transparent queue priority: every point of the score is attributable to a stated factor.

The rule is a demonstration policy, not an insurer's rule or a legal deadline. It ranks handler
attention; it never decides a claim.
"""

from claims.core.schemas import ClaimInput

TIERS = (("critical", 60), ("high", 40), ("medium", 20), ("low", 0))
POLICY = (
    "Explicit demonstration scoring rule; thresholds and weights are illustrative, "
    "not insurer rules or legal deadlines. The score orders handler attention only."
)
FLAGGED_SIMILAR_THRESHOLD = 2


def tier_for(score: int) -> str:
    return next(name for name, floor in TIERS if score >= floor)


def score_priority(
    claim: ClaimInput,
    findings: list[dict],
    predictions: dict,
    similar_cases: list[dict],
    classification: dict,
) -> dict:
    components: list[dict] = []
    reasons: list[str] = []

    def add(points: int, reason: str, *, investigate: bool = False):
        components.append({"points": points, "reason": reason})
        if investigate:
            reasons.append(reason)

    amount = claim.claim_amount
    for floor, points in ((100_000, 30), (50_000, 25), (25_000, 15), (10_000, 8)):
        if amount >= floor:
            add(points, f"Claimed amount ${amount:,.0f} is at least ${floor:,.0f}")
            break
    delay = (claim.claim_filed_date - claim.incident_date).days
    if delay > 14:
        add(
            15 if delay > 30 else 10,
            f"Submitted filing delay is {delay} days; investigate explanation, not proof of fraud.",
            investigate=True,
        )
    prior = claim.previous_claims_count
    if prior >= 3:
        add(
            15 if prior >= 5 else 10,
            "Three or more previous claims; inspect relevant history without assuming fraud.",
            investigate=True,
        )
    if any(f["kind"] == "contradiction" for f in findings):
        add(15, "Conflicting evidence requires focused handler clarification.", investigate=True)
    gaps = sum(f["kind"] == "gap" for f in findings)
    if gaps:
        add(min(10, 5 * gaps), f"{gaps} supported evidence gap(s) to resolve")
    fraud = (predictions or {}).get("fraud") or {}
    if predictions.get("available") and fraud.get("review_signal"):
        add(
            15,
            "Synthetic fraud-flag model exceeds its review threshold; sample precision is limited, "
            "so independently investigate rather than infer fraud.",
            investigate=True,
        )
    flagged = sum(bool(c.get("dataset_fraud_flag")) for c in similar_cases)
    if flagged >= FLAGGED_SIMILAR_THRESHOLD:
        add(
            10,
            f"{flagged} of {len(similar_cases)} most similar historical claims carry the dataset "
            "fraud flag (a synthetic label, not proof); compare them before relying on this claim.",
            investigate=True,
        )
    if classification.get("needs_review"):
        add(5, "Claim category is uncertain and needs handler confirmation")
    score = min(100, sum(c["points"] for c in components))
    return {
        "service_urgency": "urgent" if amount >= 50_000 else "normal",
        "investigation_priority": "elevated" if reasons else "normal",
        "score": score,
        "tier": tier_for(score),
        "components": components,
        "similar_flagged": flagged,
        "reasons": reasons,
        "policy": POLICY,
    }
