"""The Synapt query agent in every investigation: one real `trident_query` call about how to handle this kind of claim.

Synapt's Explainability pages list the answers its query agent writes, each with a confidence, the passages and procedures
it used and a Retrieval Pass Card. An investigation reads passages and the knowledge graph directly (`trident_get_chunks`,
`trident_search`, `trident_traverse`), which are retrievals, not answers, so on its own it never appears there. So that a
reviewer of the Synapt integration can see this application working through the query agent, each investigation makes one
`trident_query` call and shows its answer beside the brief, with Synapt's own confidence, passages, procedures and graph.

What is sent is fixed: the claim's type and, only when the narrative mentions theft, that. Never the narrative, names,
amounts or dates. The `task_id` is the investigation's own run ID, so the entry in Synapt's Explainability can be matched to
the run here. Display only: the answer is never evidence for the brief, is never given to the brief's models, and is not
checked by the brief's validation, because it is text a model wrote.

Synapt's documentation says it learns from the questions it answers; measured on 12 October 2026, a query alone created no
episode but a handler's feedback on it did. The owner approved one query per investigation; evaluation runs, the interactive
search and degraded runs make none.
"""

from claims.core.schemas import ClaimInput
from claims.investigation.sidechat import parse_query, plain_part, plain_text
from claims.observability import telemetry
from claims.synapt.knowledge_graph import theft_cue

TOP_K = 5


def question_for(claim: ClaimInput) -> str:
    """The one fixed question, built from the claim type alone (and a theft cue as a bare fact, never the narrative)."""
    kind = claim.claim_type.value if claim.claim_type else None
    subject = f"{'an' if kind == 'auto' else 'a'} {kind} claim" if kind else "an insurance claim"
    theft = " involving theft" if theft_cue(claim) else ""
    return (
        f"For {subject}{theft}, which documents should a claims handler request and in what order, who is responsible for "
        "each step, and what must a human claims handler review before any decision?"
    )


def run_query(ask, claim: ClaimInput, evidence_ids: set[str], run_id: str, question: str | None = None) -> dict:
    """Ask Synapt's query agent and return the answer as the run stores it. Raises when Synapt cannot answer. ``question`` is one the
    Knowledge Q&A Agent's model wrote from the claim's type and conditions (checked before it gets here); without it the fixed
    question is asked.

    The call is a span like every other Synapt call, so the live view and the trace show it with its query, the number of
    passages the answer used and Synapt's confidence."""
    question = question or question_for(claim)
    with telemetry.span("synapt.call_tool", kind="tool", tool="trident_query", purpose="query_agent", query=question, top_k=TOP_K) as trace:
        payload = ask(question, task_id=run_id, top_k=TOP_K)
        # A function when the call was made before the passages were in: the answer's passages are matched to the evidence now.
        part = parse_query(payload, evidence_ids() if callable(evidence_ids) else evidence_ids)
        trace.set(items=len(part["synapt"]["passages"]), confidence_label=part["synapt"]["confidence"]["label"])
    part["synapt"]["task_id"] = run_id
    return {"available": True, "question": question, "part": part, "task_id": run_id}


def pending(question: str, run_id: str) -> dict:
    """The state of a run whose answer has not arrived yet. The brief does not wait for it (it is display only); the answer is
    attached to the saved run when it comes, and the page picks it up as it picks up the judge's verdict."""
    return {"available": False, "pending": True, "reason": None, "question": question, "part": None, "task_id": run_id}


def unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason, "question": None, "part": None, "task_id": None}


def present(query_agent: dict | None, admin: bool) -> dict | None:
    """What a viewer may see. An administrator sees everything; everyone else sees the answer and where it came from, with
    no vendor name, scores, query ID or task ID."""
    if not query_agent or admin:
        return query_agent
    shown = dict(query_agent)
    if shown.get("part"):
        shown["part"] = plain_part(shown["part"])
    if shown.get("reason"):
        shown["reason"] = plain_text(shown["reason"])
    shown.pop("task_id", None)
    return shown

