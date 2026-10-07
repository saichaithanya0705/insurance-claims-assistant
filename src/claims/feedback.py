"""Reviewed handler feedback becomes reusable evidence.

Loop: a handler reviews a brief and rates it -> an administrator promotes the reviewed lesson ->
the lesson is retrieved as cited evidence (``handler_lesson`` provenance) in later investigations
of the same claim type, and in live mode is also ingested into the Synapt provider.

A lesson is advisory context written by a person. It carries no claim identifiers or free-text
claim descriptions, and it never decides coverage, fraud or payment.
"""

from claims.cards import LESSON_MARKER, claim_card_text
from claims.models import Evidence

GUIDANCE = (
    "Reviewer-approved handler note from a previous investigation. Advisory context only: it "
    "does not decide coverage, approve or deny a claim, authorize payment, or establish fraud."
)


def lesson_source_id(lesson_id: int) -> str:
    return f"lesson:{lesson_id}"


def lesson_document(lesson: dict, run: dict) -> str:
    claim = run.get("claim", {})
    findings = run.get("findings", [])
    kinds = {}
    for finding in findings:
        kinds[finding["kind"]] = kinds.get(finding["kind"], 0) + 1
    try:
        card = claim_card_text(claim, include_outcome=False)
    except (KeyError, ValueError, TypeError):
        card = f"{claim.get('claim_type') or 'insurance'} claim in {claim.get('state', '')}."
    summary = ", ".join(f"{count} {kind}" for kind, count in sorted(kinds.items())) or "none"
    return "\n".join(
        [
            f"# Handler lesson {lesson['id']}",
            f"{LESSON_MARKER} LESSON-{lesson['id']}",
            f"claim_type: {claim.get('claim_type') or 'unknown'}",
            f"state: {claim.get('state', 'unknown')}",
            f"situation: {card}",
            f"investigation_findings: {summary}",
            f"handler_rating: {lesson['rating']} of 5",
            f"handler_note: {lesson['note']}",
            GUIDANCE,
            "",
        ]
    )


def lesson_evidence(lesson: dict) -> Evidence:
    """Evidence built from the stored lesson row alone (no claim text or identifiers)."""
    text = "\n".join(
        [
            f"claim_type: {lesson.get('claim_type') or 'unknown'}",
            f"state: {lesson.get('state') or 'unknown'}",
            f"handler_rating: {lesson['rating']} of 5",
            f"handler_note: {lesson['note']}",
            GUIDANCE,
        ]
    )
    return Evidence(
        source_id=lesson_source_id(lesson["id"]),
        title=f"Reviewed handler lesson {lesson['id']} ({lesson.get('claim_type') or 'any type'})",
        text=text,
        provenance="handler_lesson",
    )
