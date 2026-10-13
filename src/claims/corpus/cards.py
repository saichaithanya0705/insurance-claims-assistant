"""Deterministic claim-card text and masking-safe claim identifiers.

One module owns both so that the cards uploaded to Synapt, the text used to query it, and the
keyword leg of local ranking all describe a claim in the same words.

Synapt's ingestion pipeline masks personal-looking data before indexing. A format probe against a
real tenant (see docs/SYNAPT_INTEGRATION.md) showed:

* digit-only identifiers such as ``CLM-0000000012`` become phone/SSN placeholders;
* upper-case letter tokens such as ``CLMREF-AAAAAAAABC`` are sometimes rewritten as organisations;
* state names and some postal codes (``Texas``, ``TX``, ``Georgia (GA)``) become locations;
* lower-case letter-only tokens, bands such as ``5,000-10,000`` and claim-type words survive intact.

So Synapt cards use a lower-case alias (digit 0-9 -> letter a-j, reversible with no lookup table)
and an opaque ``regionkey_xx`` token instead of the state. Human-readable text (real state names)
is used only locally.
"""

import re
from datetime import date
from itertools import pairwise

from claims.core.us_states import STATE_NAMES

_STATE_INDEX = {code: i for i, code in enumerate(sorted(STATE_NAMES))}

_TO_LETTERS = str.maketrans("0123456789", "abcdefghij")
_TO_DIGITS = str.maketrans("abcdefghij", "0123456789")
CLAIM_ID = re.compile(r"CLM-(\d{4,16})")
ALIAS = re.compile(r"\bclaimref_([a-j]{4,16})\b")
CARD_BODY = re.compile(r"claim_ref:\s*claimref_([a-j]{4,16})\b")
LESSON_MARKER = "handler_lesson_ref:"
CARD_MARKER = "claim_ref:"

AMOUNT_EDGES = (1_000, 2_500, 5_000, 10_000, 25_000, 50_000, 100_000, 250_000)
TENURE_EDGES = (1, 3, 5, 10, 20)
DELAY_EDGES = (1, 4, 8, 15, 31, 61)


def claim_alias(claim_id: str) -> str:
    """CLM-0000000012 -> claimref_aaaaaaaabc (lower-case letters only)."""
    match = CLAIM_ID.fullmatch(claim_id)
    if match is None:
        raise ValueError("Claim identifiers must look like CLM-0000000012")
    return "claimref_" + match.group(1).translate(_TO_LETTERS)


def claim_id_from_alias(alias: str) -> str:
    match = ALIAS.fullmatch(alias)
    if match is None:
        raise ValueError("Not a claim alias")
    return "CLM-" + match.group(1).translate(_TO_DIGITS)


def claim_ids_in_text(text: str) -> list[str]:
    """Claim IDs referenced by aliases (preferred) or legacy plain IDs, in order of appearance."""
    found: list[tuple[int, str]] = [
        (m.start(), claim_id_from_alias(m.group(0))) for m in ALIAS.finditer(text or "")
    ]
    found += [(m.start(), m.group(0)) for m in CLAIM_ID.finditer(text or "")]
    return list(dict.fromkeys(claim_id for _, claim_id in sorted(found)))


def card_ids_in_text(text: str) -> list[str]:
    """Claim IDs of the cards whose *body* is in ``text`` (a ``claim_ref:`` line), in order.

    Synapt splits cards into chunks by token count, so a returned chunk can end with the
    ``### history:<alias>`` header of the next card, whose body is in the following chunk. That alias
    is a neighbour in corpus order, not a match for the query, so only body aliases are counted.
    """
    return list(
        dict.fromkeys(
            "CLM-" + m.group(1).translate(_TO_DIGITS) for m in CARD_BODY.finditer(text or "")
        )
    )


def is_card_chunk(text: str) -> bool:
    """True for passages that are historical claim cards (used for ranking, never cited)."""
    return CARD_MARKER in (text or "") or ALIAS.search(text or "") is not None


def region_token(state: str) -> str:
    """Opaque stand-in for a state code, e.g. TX -> regionkey_ah; never masked as a location."""
    index = _STATE_INDEX.get(state)
    if index is None:
        raise ValueError(f"Unknown state code {state!r}")
    return "regionkey_" + f"{index:02d}".translate(_TO_LETTERS)


def _band(value: float, edges: tuple, template_low: str, template_mid: str, template_high: str):
    if value < edges[0]:
        return template_low.format(edges[0])
    for low, high in pairwise(edges):
        if value < high:
            return template_mid.format(low, high)
    return template_high.format(edges[-1])


def amount_band(amount: float) -> str:
    return _band(amount, AMOUNT_EDGES, "under {:,}", "{:,}-{:,}", "over {:,}")


def tenure_band(years: float) -> str:
    return _band(years, TENURE_EDGES, "under {} year", "{}-{} years", "over {} years")


def delay_band(days: int) -> str:
    return _band(days, DELAY_EDGES, "same day", "{}-{} days", "over {} days")


def history_band(count: int) -> str:
    return (
        "no prior claims"
        if count == 0
        else "one prior claim"
        if count == 1
        else "a few prior claims"
        if count < 4
        else "many prior claims"
    )


def _day(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def claim_card_text(
    fields: dict, *, include_outcome: bool = True, masking_safe: bool = False
) -> str:
    """Natural-language description derived only from structured fields (nothing invented).

    ``masking_safe`` replaces the state with an opaque token so the text survives Synapt's PII
    masking; use it for everything sent to or compared against Synapt."""
    state = fields["state"]
    delay = (_day(fields["claim_filed_date"]) - _day(fields["incident_date"])).days
    amount = float(fields["claim_amount"])
    tenure = float(fields["policyholder_tenure_years"])
    prior = int(fields["previous_claims_count"])
    kind = fields.get("claim_type") or "insurance"
    place = (
        region_token(state)
        if masking_safe
        else f"{STATE_NAMES.get(state, state)} ({state})"
    )
    parts = [
        f"{kind} claim in {place}.",
        (
            f"Claimed amount band {amount_band(amount)} USD (about ${amount:,.0f}); "
            f"deductible ${float(fields['deductible']):,.0f}."
        ),
        (
            f"Policyholder tenure {tenure_band(tenure)}; {history_band(prior)} "
            f"({prior} on the policy)."
        ),
        f"Filed {delay} day{'s' if delay != 1 else ''} after the incident ({delay_band(delay)}).",
    ]
    status, days = fields.get("claim_status"), fields.get("days_to_resolution")
    if include_outcome and status in ("approved", "denied"):
        try:
            parts.append(f"Outcome {status} after {int(float(days))} days.")
        except (TypeError, ValueError, OverflowError):
            parts.append(f"Outcome {status}.")
    elif include_outcome and status in ("pending", "under_review"):
        parts.append(f"Status {status.replace('_', ' ')}; no final outcome yet.")
    return " ".join(parts)


def claim_ticket(fields: dict) -> dict:
    """The columns Synapt's ticket store embeds (title, description, category, region), for an uploaded ticket and for a
    claim being looked up alike, so both are described in the same words. Masking-safe and outcome-free."""
    delay = (_day(fields["claim_filed_date"]) - _day(fields["incident_date"])).days
    kind = fields.get("claim_type") or ""
    return {
        "title": (
            f"{(kind or 'insurance').capitalize()} claim, {amount_band(float(fields['claim_amount']))} USD, "
            f"filed {delay} days after the incident"
        ),
        "description": claim_card_text(fields, include_outcome=False, masking_safe=True),
        "category": kind,
        "region": region_token(fields["state"]),
    }
