"""A handler's verdict on an answer Synapt's query agent wrote, sent back to Synapt (`trident_feedback`).

Two kinds of answer can be rated: the one every investigation asks for (`target` "investigation") and a handling answer from
the side chat (`target` "side:<id>"). The handler chooses in plain words, and each choice maps to a verdict Synapt defines:

    "Yes, it helped"  -> deflected      "Partly"  -> partial      "No"  -> not_deflected

The query ID Synapt returned is looked up here from the saved run, never taken from the request, so a person can only rate an
answer that belongs to a case they may open. One verdict per answer; nothing is saved unless Synapt accepted it, so a failed
send can be tried again. The optional note is masked of personal identifiers first. The audit log gets one event; the brief,
its evidence and its checks are not touched.
"""

import sqlite3

from claims.agents import access
from claims.core.schemas import redact_personal_data

CHOICES = {"helpful": "deflected", "partly": "partial", "not_helpful": "not_deflected"}
MAX_REASON = 300
INVESTIGATION = "investigation"


class FeedbackError(Exception):
    """A verdict that cannot be sent; `status` is the HTTP status to use."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _synapt_part(parts):
    return next((p for p in parts or [] if p.get("source") == "synapt" and p.get("status") == "ok" and p.get("synapt")), None)


def resolve(run: dict, side_questions: list[dict], target: str) -> str:
    """The query ID Synapt returned for the answer being rated, from what this application saved."""
    if target == INVESTIGATION:
        part = (run.get("query_agent") or {}).get("part")
        query_id = ((part or {}).get("synapt") or {}).get("query_id")
    elif target.startswith("side:") and target[5:].isdigit():
        item = next((q for q in side_questions if q["id"] == int(target[5:])), None)
        part = _synapt_part(((item or {}).get("body") or {}).get("parts"))
        query_id = ((part or {}).get("synapt") or {}).get("query_id")
    else:
        raise FeedbackError("Unknown answer.", 404)
    if not isinstance(query_id, str) or not query_id:
        raise FeedbackError("There is no knowledge-base answer here to rate.", 404)
    return query_id


def submit(store, adapter, run: dict, *, target: str, choice: str, reason: str | None, owner) -> dict:
    if choice not in CHOICES:
        raise FeedbackError("Choose Yes, Partly or No.", 422)
    run_id = run["run_id"]
    query_id = resolve(run, store.side_questions(run_id), target)
    if any(f["target"] == target for f in store.query_feedback(run_id)):
        raise FeedbackError("Feedback was already sent for this answer.", 409)
    send = getattr(adapter, "send_feedback", None)
    if send is None:
        raise FeedbackError("Synapt is not connected in this environment, so feedback cannot be sent.", 503)
    note = redact_personal_data((reason or "").strip())[:MAX_REASON] or None
    verdict = CHOICES[choice]
    try:
        with access.acting_as("reviewer"):
            send(query_id, verdict, caller_type="user", reason=note)
    except Exception:  # noqa: BLE001 - a provider's error text never reaches the page
        raise FeedbackError("Synapt could not take the feedback right now. Try again in a moment.", 502) from None
    try:
        saved = store.add_query_feedback(run_id, target, query_id, owner, choice, verdict, note)
    except sqlite3.IntegrityError:
        raise FeedbackError("Feedback was already sent for this answer.", 409) from None
    store.event(run_id, "query_feedback", {"target": target, "choice": choice, "verdict": verdict})
    return {"target": target, "choice": choice, "sent_at": saved["sent_at"]}


def listing(store, run_id: str) -> list[dict]:
    """What has been rated for this case: the target, the plain choice and when, never the query ID or the verdict wording."""
    return [{"target": f["target"], "choice": f["choice"], "sent_at": f["sent_at"]} for f in store.query_feedback(run_id)]
