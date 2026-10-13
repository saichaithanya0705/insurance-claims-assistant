"""Side chat: questions about the claim being investigated, answered from the right source and kept apart from the brief.

A handler asks on the side: "which documents do I request?", "what was the claimed amount net of the deductible?", "why is
the priority low?", "how were claims like this settled?". Each kind of question has a different source of truth, so a router
sends it to the one that can answer it, and a mixed question gets one labelled part per source:

* handling knowledge (documents to request, who does a step, in what order)  -> Synapt's query agent (`trident_query`)
* the claim's own facts (amount, dates, documents reported)                   -> the saved run, exactly, no model
* the brief (a gap, a recommendation, the priority and why)                   -> the saved run's findings and priority
* past claims (how similar claims settled, median days)                       -> the run's DuckDB cohort figures
* estimates (amount, days, the fraud-flag signal)                             -> the run's model predictions
* provenance (what was retrieved, what backs a finding)                       -> the run's evidence and graph
* decisions (approve, deny, pay, is it fraud, is it covered)                  -> declined, with what to look at instead

Nothing here changes the investigation: the run, its evidence, findings, validation and audit are read, never written. A side
answer is stored in its own table. Only a handling question reaches Synapt. Synapt's documentation says it learns from the
questions it answers, so identical questions are answered from the saved answer, the volume is limited, and no personal text
is sent: the question is masked, and the only claim context is its type.
"""

import re
import threading
import time
from collections import deque
from datetime import date

from claims.core.schemas import redact_personal_data
from claims.corpus.cards import is_card_chunk

MAX_QUESTION = 500
MIN_QUESTION = 3
MAX_PER_RUN = 40
MAX_PER_MINUTE = 6
MAX_PARTS = 3

SOURCE_NAMES = {
    "claim": "The submitted claim",
    "brief": "This brief",
    "history": "Past claims (DuckDB)",
    "estimates": "Model estimates",
    "evidence": "Retrieved evidence",
    "synapt": "Synapt knowledge base",
    "boundary": "Decision boundary",
    "outside": "Outside this tool",
    "unknown": "Not understood",
}


class SideChatError(Exception):
    """A question the side chat will not answer; `status` is the HTTP status to use."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ----- routing -----------------------------------------------------------------------------------------------------

_DOCUMENT_HAVE = re.compile(r"\b(?:submitted|provided|reported|attached|on file|available|supplied|uploaded|has the claimant|did the claimant|do we have|have we)\b")
_DOCUMENT_NEED = re.compile(r"\b(?:request|requested|need|needed|require|required|ask for|asking for|missing|should|must|collect|obtain|get from|chase)\b")

LEXICON: dict[str, list[re.Pattern]] = {
    intent: [re.compile(p) for p in patterns]
    for intent, patterns in {
        "decision": [
            r"\bshould (?:we|i|the (?:handler|company|insurer)) (?:approve|deny|reject|pay|settle|decline|accept|refuse)\b",
            r"\b(?:approve|deny|reject|decline|refuse) (?:this|the|it)\b",
            r"\bis (?:this|it|the claim|the claimant)\b.{0,25}\b(?:fraud\w*|legit\w*|valid|genuine|lying|honest|true|covered|eligible|payable|liable)\b",
            r"\bwill (?:this|it|the claim) be (?:approved|denied|paid|rejected|accepted)\b",
            r"\b(?:coverage|payout|settlement|approval|denial) decision\b",
            r"\bis (?:this|it|that)\b.{0,20}\bcovered\b",
            r"\bcommitt?ed fraud\b|\bis .{0,20}\bscam\w*\b",
            r"\bhow much (?:should|will|do|can) (?:we|i) (?:pay|settle)\b",
            r"\bpay (?:out )?(?:this|the) claim\b",
            # a payment or offer: "how much should we offer for the jewelry", "what settlement amount"
            r"\bhow much (?:should|will|would|do|can) (?:we|i|the (?:company|insurer))\b.{0,20}\b(?:pay|settle|offer|reimburse|compensate|reserve)\b|\bwhat (?:should|would|will) (?:we|the (?:company|insurer)) (?:pay|offer)\b|\b(?:make|what) (?:an )?offer\b|\bsettlement (?:amount|offer|figure)\b",
            # a judgement of the claimant's honesty
            r"\bis (?:this|it|the claim|the claimant|the (?:policyholder|insured))\b.{0,25}\b(?:telling the truth|credible|trustworthy|believable|dishonest|exaggerat\w*|faking|staged)\b",
            # coverage: this tool holds no policy wording
            r"\b(?:wear[- ]and[- ]tear|exclusions?)\b.{0,25}\b(?:apply|applies|applicable|relevant|cover\w*)\b|\bdoes (?:the|this|our) (?:policy|coverage|insurance|contract)\b.{0,30}\b(?:cover|apply|include|exclude|pay)\w*\b",
        ],
        "outside": [
            # facts about the outside world, which no saved record or knowledge base here can confirm
            r"\bweather\b|\brain(?:fall|ed)?\b|\btemperature\b|\bwas there (?:a|any) (?:storm|hail|flood|fire|earthquake)\b|\bnews (?:report|coverage)\b|\bverify (?:that )?the (?:storm|hail|fire|flood|weather)\b",
            # personal contact or identity details, which are masked before anything is stored
            r"\b(?:phone|telephone|mobile|cell) (?:number|no)\b|\be-?mail address\b|\b(?:home|mailing|street|billing) address\b|\bsocial security\b|\bssn\b|\bdate of birth\b|\bdob\b|\bbank (?:account|details)\b|\bcontact (?:details|information|info)\b",
        ],
        "claim_facts": [
            r"\b(?:how much|claimed|claim amount|amount (?:claimed|of the claim)|what(?:'s| is| was) the amount)\b",
            r"\bdeductible\b",
            r"\bnet exposure\b",
            r"\b(?:incident|filing|filed|loss) date\b|\bwhen (?:was|did|were)\b",
            r"\bhow many days (?:after|between|from|before)\b|\bfiling delay\b|\bdelay in filing\b|\breport(?:ed)? late\b",
            r"\bdays? (?:passed|elapsed|went by)\b|\bbetween the incident and\b|\bhow (?:long|many days) (?:after|since) the incident\b|\bhow late\b",
            r"\bwhich state\b|\bwhat state\b|\bwhere (?:did|was) (?:it|the (?:incident|loss))\b",
            r"\btenure\b|\bhow long (?:has|have) (?:the )?(?:policyholder|insured|customer|claimant)\b",
            r"\b(?:prior|earlier|previous) claims?\b(?! like)|\bclaims? (?:history|count)\b",
            r"\bwhat (?:type|kind) of claim\b|\bclaim type\b",
        ],
        # the bare words "policyholder" and "claimant" only count when nothing else is recognised: "what should I ask a claimant who..."
        # is a handling question and must not also dump the whole claim record
        "claim_weak": [
            r"\bpolicyholder\b|\bclaimant\b(?! reported)",
        ],
        "brief": [
            r"\bpriority\b|\bpriority (?:score|tier)\b|\burgen\w*\b|\bqueue\b|\btier\b",
            r"\b(?:gap|gaps)\b|\bunresolved\b|\bwhat(?:'s| is) missing\b|\bconcerns?\b",
            r"\bcontradict\w*\b|\bconflict\w*\b|\binconsisten\w*\b",
            r"\brecommend\w*\b|\bnext steps?\b|\bwhat should (?:i|we) do (?:next|now|first)\b|\bnext actions?\b",
            r"\bfindings?\b|\bthe brief\b|\bthis brief\b|\bsummar\w*\b",
            r"\bvalidat\w*\b|\bjudge\b|\bindependent review\b|\bchecks? (?:passed|failed)\b",
            r"\bwhy (?:is|was|does|did|are)\b",
        ],
        "history": [
            r"\bsimilar (?:claims?|cases?)\b|\bclaims? like (?:this|these|it)\b|\bcomparable\b|\bcomparison\b",
            r"\bpast claims\b|\bhistorical\b|\bhistory of (?:similar|such)\b",
            r"\b(?:usually|typically|normally|generally) (?:settled?|resolved?|approved|denied|handled|take[sn]?)\b",
            r"\b(?:median|average|typical) (?:days|time|duration)\b|\bhow long do(?:es)?\b|\btime to (?:settle|resolve)\b",
            r"\bapproval (?:rate|share)\b|\bapproved share\b|\bdenied share\b|\bdenial rate\b|\bshare (?:of|that) (?:were )?(?:approved|denied)\b",
            r"\bcohort\b|\bstatistic\w*\b|\bhow many (?:similar|such|comparable)\b",
            r"\bclaims? (?:from|in|for) (?:this|the same|that|my) state\b|\bin your (?:records|data|dataset|history)\b|\bany (?:past |previous |earlier |historical )?claims? (?:from|in|for)\b",
        ],
        "estimates": [
            r"\bestimat\w*\b|\bpredict\w*\b|\bforecast\w*\b",
            r"\bfraud[- ]flag\b|\bfraud (?:score|signal|risk|indicator|probability)\b|\bflag(?:ged)? signal\b|\breview signal\b",
            r"\bmodel (?:says|score|output|prediction)\b|\bexpected (?:amount|days|resolution)\b|\bresolution time\b",
            r"\b(?:confiden\w*|reliab\w*|accura\w*|certain\w*|trust\w*)\b.{0,30}\b(?:model|estimates?|predictions?|amount|interval|score)\b|\b(?:model|estimates?|predictions?)\b.{0,30}\b(?:confiden\w*|reliab\w*|accura\w*)\b|\b(?:confidence )?interval\b",
        ],
        "sources": [
            r"\bsources?\b|\bcited\b|\bcitations?\b|\bwhere did (?:this|that|you|it) (?:come|get)\b|\bback(?:s|ed)? (?:up|this|the)\b",
            r"\bevidence\b(?! gap)|\bretriev\w*\b|\bprovenance\b|\bwhich passages\b",
            r"\bknowledge graph\b|\bgraph (?:procedure|path)\b|\bwhich procedures? (?:was|were) (?:used|found|retrieved)\b",
        ],
        "handling": [
            r"\bprocedures?\b|\bsop\b|\bchecklist\b|\bprotocol\b|\bguideline\w*\b|\bplaybook\b",
            r"\bhow (?:do|should|can|would) (?:i|we|the handler) (?:handle|process|proceed|approach|treat|investigate|verify|confirm)\b",
            r"\bwhat (?:should|do|must|can) (?:i|we) (?:request|ask|collect|obtain|verify|confirm|check|require)\b",
            r"\bwhich (?:documents?|evidence|forms?|reports?) (?:should|must|need|to)\b|\bwhat (?:documents?|evidence|paperwork) (?:should|must|need|are needed|are required|to)\b",
            r"\bwho (?:is responsible|does|should do|handles|performs)\b|\bresponsible for\b|\bstep[- ]by[- ]step\b|\bin what order\b|\bwhich order\b|\bsteps? (?:to|for|of|in)\b|\bwhat (?:does|do) the (?:procedure|sop)\b",
            r"\bpolice report\b|\brepair estimate\b|\bincident statement\b|\bdamage assessment\b|\binventory list\b|\bloss assessment\b",
            r"\bpre-?requisite\b|\bhuman review\b|\bboundary\b|\bescalat\w*\b",
        ],
    }.items()
}
PRIORITY = ["decision", "outside", "handling", "claim_facts", "brief", "history", "estimates", "sources"]


def normalize(question: str) -> str:
    return re.sub(r"\s+", " ", (question or "").strip().lower())


def route(question: str) -> dict:
    """Which sources can answer, and the words that decided it.

    Documents are the one ambiguous word: 'which documents were submitted' is the claim record, 'which documents should I
    request' is handling knowledge. A question that is understood by none of the patterns but reads like a real question
    goes to Synapt, flagged as a fallback; one that does not read like a question is not sent anywhere."""
    q = normalize(question)
    hits: dict[str, list[str]] = {}
    for intent, patterns in LEXICON.items():
        found = [m.group(0) for p in patterns for m in p.finditer(q)]
        if found:
            hits[intent] = found
    weak = hits.pop("claim_weak", None)
    if weak and not hits:
        hits["claim_facts"] = weak
    if re.search(r"\bdocuments?\b|\bpaperwork\b", q):
        if _DOCUMENT_HAVE.search(q) and not _DOCUMENT_NEED.search(q):
            hits.setdefault("claim_facts", []).append("documents (reported)")
        elif _DOCUMENT_NEED.search(q):
            hits.setdefault("handling", []).append("documents (needed)")
            if hits.get("claim_facts") == ["documents (reported)"]:
                hits.pop("claim_facts")
        elif not hits:  # a bare mention of documents, and nothing else to go on: the claim's own record
            hits["claim_facts"] = ["documents (reported)"]
    # "claimed/claim" words alone must not drag a handling or decision question into the claim record
    if "decision" in hits:
        hits = {"decision": hits["decision"], **{k: v for k, v in hits.items() if k in ("brief", "history")}}
    elif "outside" in hits:
        # "what was the weather on the incident date" must not be answered with the incident date
        hits = {"outside": hits["outside"]}
    ordered = sorted(hits, key=lambda i: (-len(hits[i]), PRIORITY.index(i)))[:MAX_PARTS]
    fallback = False
    if not ordered:
        words = re.findall(r"[a-z']{2,}", q)
        if len(words) >= 3 and (q.endswith("?") or re.match(r"(?:what|which|who|how|when|where|why|can|should|do|does|is|are|tell|explain|list|give|show)\b", q)):
            ordered, fallback = ["handling"], True
            hits["handling"] = ["(no specific pattern; general question)"]
    return {"intents": ordered, "matched": {i: hits[i][:4] for i in ordered}, "fallback": fallback}


# ----- the saved run, read safely ---------------------------------------------------------------------------------

def _money(value):
    return f"${value:,.2f}" if isinstance(value, int | float) else "not recorded"


def _days_between(first, last):
    try:
        return (date.fromisoformat(str(last)[:10]) - date.fromisoformat(str(first)[:10])).days
    except (TypeError, ValueError):
        return None


def _cap(text, limit=360):
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _part(source, title, *, status="ok", text="", facts=None, items=None, table=None, notes=None, cites=None, synapt=None):
    return {
        "source": source, "title": title, "status": status, "text": text, "facts": facts or [], "items": items or [],
        "table": table, "notes": notes or [], "cites": list(dict.fromkeys(cites or [])), "synapt": synapt,
    }


def _has(q, *patterns):
    return any(re.search(p, q) for p in patterns)


def _net(amount, deductible) -> str:
    if not isinstance(amount, int | float) or not isinstance(deductible, int | float):
        return "not recorded"
    left = amount - deductible
    if left > 0:
        return _money(left)
    return "$0.00 (the claimed amount is at the deductible)" if left == 0 else f"$0.00 (the claimed amount is {_money(-left)} below the deductible)"


def answer_claim(run: dict, q: str) -> dict:
    claim = run.get("claim") or {}
    amount, deductible = claim.get("claim_amount"), claim.get("deductible")
    delay = _days_between(claim.get("incident_date"), claim.get("claim_filed_date"))
    catalog = {
        "type": ("Claim type", str(claim.get("claim_type") or "not recorded").capitalize()),
        "state": ("State", claim.get("state") or "not recorded"),
        "amount": ("Claimed amount", _money(amount)),
        "deductible": ("Deductible", _money(deductible)),
        "net": ("Amount net of deductible", _net(amount, deductible)),
        "incident": ("Incident date", claim.get("incident_date") or "not recorded"),
        "filed": ("Filed", claim.get("claim_filed_date") or "not recorded"),
        "delay": ("Filed after the incident", f"{delay} day{'' if delay == 1 else 's'}" if delay is not None else "not recorded"),
        "tenure": ("Policyholder tenure", f"{claim.get('policyholder_tenure_years')} years" if claim.get("policyholder_tenure_years") is not None else "not recorded"),
        "prior": ("Earlier claims on the policy", str(claim.get("previous_claims_count")) if claim.get("previous_claims_count") is not None else "not recorded"),
        "documents": ("Documents reported available", ", ".join(claim.get("provided_documents") or []) or "none reported"),
    }
    wanted = []
    if _has(q, r"\bhow much\b|\bclaimed\b|\bamount\b"):
        wanted += ["amount", "deductible", "net"]
    if _has(q, r"\bdeductible\b") and "deductible" not in wanted:
        wanted += ["deductible", "net"]
    if _has(q, r"\bnet\b|\bexposure\b") and "net" not in wanted:
        wanted += ["amount", "deductible", "net"]
    if _has(q, r"\bdate\b|\bwhen\b|\bfiled\b|\bfiling\b|\bdelay\b|\bhow many days\b|\bincident\b|\blate\b"):
        wanted += ["incident", "filed", "delay"]
    if _has(q, r"\bstate\b|\bwhere\b"):
        wanted += ["state"]
    if _has(q, r"\btenure\b|\bhow long (?:has|have|had) (?:the )?(?:policyholder|insured|customer|claimant)"):
        wanted += ["tenure"]
    if _has(q, r"\bprior\b|\bprevious\b|\bearlier\b|\bhistory\b|\bclaims? count\b"):
        wanted += ["prior"]
    if _has(q, r"\bdocuments?\b|\bpaperwork\b"):
        wanted += ["documents"]
    if _has(q, r"\btype\b|\bkind\b"):
        wanted += ["type"]
    keys = list(dict.fromkeys(wanted)) or ["type", "state", "amount", "deductible", "net", "incident", "filed", "delay", "tenure", "prior", "documents"]
    facts = [{"label": catalog[k][0], "value": catalog[k][1]} for k in keys]
    text = "; ".join(f"{label.lower()} {value}" for label, value in ((f["label"], f["value"]) for f in facts[:4]))
    return _part(
        "claim", "From the submitted claim", text=text[:1].upper() + text[1:] + "." if text else "", facts=facts,
        notes=["As submitted; not independently verified. Document names only, no document content was read."],
        cites=["claim:input"],
    )


def answer_brief(run: dict, q: str) -> dict:
    findings = run.get("findings") or []
    recs = run.get("recommendations") or []
    priority = run.get("priority") or {}
    validation = run.get("validation") or {}
    judge = run.get("judge") or {}
    items, cites, notes, text = [], [], [], ""
    want_priority = _has(q, r"\bpriority\b|\burgen\w*\b|\bqueue\b|\btier\b|\bscore\b")
    want_gaps = _has(q, r"\bgap\w*\b|\bmissing\b|\bunresolved\b|\bconcern\w*\b")
    want_contra = _has(q, r"\bcontradict\w*\b|\bconflict\w*\b|\binconsisten\w*\b")
    want_recs = _has(q, r"\brecommend\w*\b|\bnext\b|\baction\w*\b|\bwhat should\b")
    want_checks = _has(q, r"\bvalidat\w*\b|\bjudge\b|\bindependent\b|\bchecks?\b|\bpassed\b")
    if want_priority and priority.get("score") is not None:
        text = f"The handling priority is {priority.get('tier')} ({priority.get('score')}/100). The score only orders handler attention; it says nothing about coverage or fraud."
        items = [{"text": f"+{c.get('points')}: {c.get('reason')}", "cites": [], "tag": "points"} for c in priority.get("components") or []]
        if priority.get("policy"):
            notes.append(_cap(priority["policy"], 240))
    elif want_checks:
        passed = validation.get("passed")
        text = ("The brief passed its checks." if passed else "The brief did not pass every check.") + (f" Scope: {validation.get('scope')}." if validation.get("scope") else "")
        items = [{"text": f"{'Passed' if c.get('passed') else 'Failed'}: {c.get('label')}", "cites": [], "tag": "check"} for c in validation.get("checks") or []]
        if judge.get("status"):
            notes.append(f"Independent review: {judge.get('status')}." + (f" {judge.get('reason')}" if judge.get("status") == "pending" and judge.get("reason") else ""))
    elif want_contra:
        chosen = [f for f in findings if f.get("kind") == "contradiction"]
        text = f"{len(chosen)} contradiction{'' if len(chosen) == 1 else 's'} found in the brief." if chosen else "The brief found no contradictions."
        items = [{"text": f["text"], "cites": f.get("source_ids") or [], "tag": "contradiction"} for f in chosen]
    elif want_gaps:
        chosen = [f for f in findings if f.get("kind") in ("gap", "risk_indicator")]
        text = f"{len(chosen)} gap or concern{'' if len(chosen) == 1 else 's'} to resolve." if chosen else "The brief found no evidence gaps or concerns."
        items = [{"text": f["text"], "cites": f.get("source_ids") or [], "tag": f["kind"]} for f in chosen]
    elif want_recs:
        text = f"{len(recs)} recommended action{'' if len(recs) == 1 else 's'}; the handler decides what happens next." if recs else "The brief has no recommended actions."
        items = [{"text": f"{r.get('action')}: {_cap(r.get('reason'), 300)}", "cites": r.get("source_ids") or [], "tag": "action"} for r in recs]
    else:
        attention = [f for f in findings if f.get("kind") in ("contradiction", "gap", "risk_indicator")]
        text = (
            f"The brief has {len(findings)} finding{'' if len(findings) == 1 else 's'}; {len(attention)} need{'s' if len(attention) == 1 else ''} attention."
            + (f" Handling priority is {priority.get('tier')} ({priority.get('score')}/100)." if priority.get("score") is not None else "")
        )
        items = [{"text": f["text"], "cites": f.get("source_ids") or [], "tag": f["kind"]} for f in attention] or [
            {"text": f["text"], "cites": f.get("source_ids") or [], "tag": f["kind"]} for f in findings[:4]
        ]
    for item in items:
        cites += item["cites"]
    return _part("brief", "From this brief", text=text, items=items, notes=notes, cites=cites)


def answer_history(run: dict, q: str) -> dict:
    cohort = run.get("cohort") or {}
    if not cohort.get("available"):
        reason = cohort.get("reason") or "cohort statistics were not computed for this run"
        return _part("history", "Past claims, from the full dataset", status="unavailable", text=f"There are no exact past-claim figures for this run: {reason}.")
    names = {"exact": "Same description", "type_amount_history": "Same type, amount and history", "type": "Same claim type"}
    rows = cohort.get("cohorts") or []
    if _has(q, r"\bexact\b|\bsame description\b|\bidentical\b"):
        rows = [r for r in rows if r.get("key") == "exact"] or rows
    elif _has(q, r"\bany state\b|\bamount\b.*\bhistory\b"):
        rows = [r for r in rows if r.get("key") == "type_amount_history"] or rows
    elif _has(q, r"\ball \w+ claims\b|\bwhole\b|\boverall\b|\bwhole type\b"):
        rows = [r for r in rows if r.get("key") == "type"] or rows

    def pct(v):
        return f"{v * 100:.1f}%" if isinstance(v, int | float) else "—"

    table = {
        "columns": ["Past claims compared", "Claims", "Approved", "Median days to settle", "Synthetic fraud flag"],
        "rows": [
            [
                names.get(r.get("key"), "Comparison group"), f"{r.get('claims'):,}" if isinstance(r.get("claims"), int) else "—", pct(r.get("approved_share")),
                f"{r.get('median_days'):g} (p25–p75 {r.get('p25_days'):g}–{r.get('p75_days'):g})" if isinstance(r.get("median_days"), int | float) and isinstance(r.get("p25_days"), int | float) and isinstance(r.get("p75_days"), int | float) else "—",
                pct(r.get("flag_rate")),
            ]
            for r in rows
        ],
    }
    lead = next((r for r in rows if r.get("sufficient")), rows[0] if rows else None)
    text = ""
    if lead:
        text = (
            f"Among {lead.get('claims'):,} past claims in “{names.get(lead.get('key'), 'the closest group')}”, {pct(lead.get('approved_share'))} were approved and the median time "
            f"to settle was {lead.get('median_days'):g} days." if isinstance(lead.get("claims"), int) and isinstance(lead.get("median_days"), int | float) else "Exact figures are in the table."
        )
    similar = [c for c in run.get("similar_cases") or [] if not c.get("open_case")]
    notes = [
        "Exact statistics from the full dataset, computed by DuckDB, not by a model or by Synapt. The dataset is synthetic.",
        "Only approved or denied claims closed before " + str(cohort.get("cutoff") or "the cutoff") + " are counted. They describe past claims and say nothing about this one.",
    ]
    if similar:
        approved = sum(c.get("claim_status") == "approved" for c in similar)
        notes.append(f"Of the {len(similar)} closest settled comparison cases, {approved} were approved and {len(similar) - approved} denied.")
    if _has(q, r"(?:over|above|more than|under|below|less than|at least|exceed\w*) \$?\d"):
        notes.insert(0, "These figures are for three fixed groups of past claims and cannot be re-cut for a different amount; 'Same type, amount and history' is the closest group to a question about a size of claim.")
    claim_state = (run.get("claim") or {}).get("state")
    if similar and claim_state and _has(q, r"\bstate\b"):
        same = sum(c.get("state") == claim_state for c in similar)
        notes.insert(0, (
            f"{same} of the {len(similar)} closest settled comparison cases are from {claim_state}. The exact figures in the table are not split by state."
            + ("" if same else f" None is from {claim_state}, which does not by itself mean the dataset holds no claims from there.")
        ))
    return _part("history", "Past claims, from the full dataset", text=text, table=table, notes=notes)


def answer_estimates(run: dict, q: str) -> dict:
    p = run.get("predictions") or {}
    if not p.get("available"):
        return _part("estimates", "Model estimates", status="unavailable", text="Model estimates are not available for this run.")
    amount, days, fraud = p.get("amount") or {}, p.get("resolution") or {}, p.get("fraud") or {}
    focus_fraud = _has(q, r"\bfraud\b|\bflag\b|\bsignal\b")
    facts, items = [], []
    if fraud.get("available"):
        threshold = fraud.get("review_threshold")
        facts.append({"label": "Synthetic fraud-flag score", "value": f"{fraud.get('score'):.1%}" if isinstance(fraud.get("score"), int | float) else "—"})
        if isinstance(threshold, int | float):
            facts.append({"label": "Review threshold", "value": f"{threshold:.1%}"})
        facts.append({"label": "Review signal", "value": "Above the threshold: worth a closer look" if fraud.get("review_signal") else "Below the threshold"})
        for c in (fraud.get("local_explanation") or {}).get("contributions", [])[:3]:
            items.append({"text": f"{str(c.get('feature')).replace('_', ' ').capitalize()} = {c.get('value')} (typical {c.get('typical_value')}): effect {c.get('effect'):+.3f}", "cites": [], "tag": "effect"})
    if not focus_fraud or not fraud.get("available"):
        if amount.get("available"):
            lo, hi = (amount.get("interval") or [None, None])[:2]
            facts.append({"label": "Estimated claim amount", "value": f"{_money(amount.get('estimate'))} (90% interval {_money(lo)} to {_money(hi)})"})
        if days.get("available"):
            lo, hi = (days.get("interval") or [None, None])[:2]
            facts.append({"label": "Estimated days to resolve", "value": f"{days.get('estimate'):.1f} (90% interval {lo:.1f} to {hi:.1f})" if isinstance(lo, int | float) and isinstance(hi, int | float) and isinstance(days.get("estimate"), int | float) else str(days.get("estimate"))})
    text = (
        "The model's score estimates the dataset's synthetic fraud flag, not proven fraud, and it does not decide anything."
        if focus_fraud and fraud.get("available") else
        "These estimates describe patterns in synthetic past claims; they are not a decision about this claim."
    )
    notes = list((p.get("limitations") or [])[:2])
    if items:
        notes.insert(0, "One-at-a-time substitution of a typical claim's value; not additive or causal.")
    if _has(q, r"confiden|reliab|accura|certain|trust|interval"):
        notes.insert(0, "The 90% interval is the range the model expects the outcome to fall in nine times out of ten across past claims; a wider interval means less certainty, and a claim far from the past claims the model learned from is the least reliable.")
    return _part("estimates", "Model estimates", text=text, facts=facts, items=items, notes=notes)


def answer_evidence(run: dict, q: str) -> dict:
    evidence = run.get("evidence") or []
    graph = run.get("graph") or {}
    passages = [e for e in evidence if e.get("provenance") == "synapt" and not str(e.get("source_id", "")).startswith("graph:")]
    procedures = [e for e in evidence if str(e.get("source_id", "")).startswith("graph:")]
    history = [e for e in evidence if str(e.get("source_id", "")).startswith("history:")]
    lessons = [e for e in evidence if e.get("provenance") == "handler_lesson"]
    cited = {s for f in run.get("findings") or [] for s in f.get("source_ids") or []} | {s for r in run.get("recommendations") or [] for s in r.get("source_ids") or []}
    items = [{"text": f"{e.get('title')}" + (" (cited in the brief)" if e.get("source_id") in cited else ""), "cites": [e.get("source_id")], "tag": "procedure"} for e in procedures]
    items += [{"text": f"{e.get('title')}" + (" (cited in the brief)" if e.get("source_id") in cited else ""), "cites": [e.get("source_id")], "tag": "passage"} for e in passages]
    text = (
        f"This brief drew on {len(passages)} knowledge-base passage{'' if len(passages) == 1 else 's'}, "
        f"{len(procedures)} procedure{'' if len(procedures) == 1 else 's'} read from the knowledge graph, "
        f"{len(history)} historical comparison{'' if len(history) == 1 else 's'}"
        + (f" and {len(lessons)} reviewed handler lesson{'' if len(lessons) == 1 else 's'}" if lessons else "")
        + ", plus the submitted claim."
    )
    notes = []
    if graph.get("available"):
        notes.append(f"The knowledge graph was searched and walked with {graph.get('calls')} read-only calls; each procedure lists the passages it was extracted from.")
    return _part("evidence", "Retrieved evidence", text=text, items=items, notes=notes, cites=[i["cites"][0] for i in items])


def answer_boundary(run: dict, q: str) -> dict:
    return _part(
        "boundary", "I can't decide that", status="declined",
        text=(
            "Whether to approve, deny, pay or settle a claim, and whether it is fraudulent or covered, is for a human claims handler. "
            "This tool prepares a brief to support that review and never decides it."
        ),
        items=[
            {"text": "Ask what is missing or contradictory in the brief.", "cites": [], "tag": "try"},
            {"text": "Ask how claims like this one were settled in the past (exact figures, not a prediction for this claim).", "cites": [], "tag": "try"},
            {"text": "Ask which documents the handling procedure says to request.", "cites": [], "tag": "try"},
        ],
        notes=["No policy wording is held, so coverage cannot be assessed here."],
    )


def answer_outside(run: dict, q: str) -> dict:
    """Weather and other events in the world, and a person's contact or identity details: nothing here holds them, and nothing is guessed."""
    if _has(q, r"\bweather\b|\brain\w*\b|\btemperature\b|\bstorm\b|\bhail\b|\bflood\b|\bfire\b|\bearthquake\b|\bnews\b"):
        text = "This tool can't look up events in the outside world, such as the weather on a date. What the claimant reports stays unverified until a document or an independent source confirms it."
        tries = ["Ask which documents the handling procedure says to request to confirm the event.", "Ask what is missing or contradictory in the brief."]
    else:
        text = "The saved claim holds no names, phone numbers, addresses or other contact or identity details, and personal data is masked before anything is stored. Look in the claim or policy system."
        tries = ["Ask what the submitted claim does record (type, state, dates, amounts, documents).", "Ask which documents the handling procedure says to request."]
    return _part("outside", "Not something this tool holds", status="unavailable", text=text, items=[{"text": t, "cites": [], "tag": "try"} for t in tries])


def answer_unknown(run: dict, q: str) -> dict:
    return _part(
        "unknown", "I didn't catch what you want to know", status="unavailable",
        text="Try asking about the claim's details, why the brief says something, how similar claims settled, an estimate, where the evidence came from, or how to handle it (documents to request, who does a step).",
    )


OFFLINE = {
    "claim_facts": answer_claim, "brief": answer_brief, "history": answer_history, "estimates": answer_estimates,
    "sources": answer_evidence, "decision": answer_boundary, "outside": answer_outside,
}


# ----- Synapt's query agent ---------------------------------------------------------------------------------------

_CHUNK_SOURCE = re.compile(r"source_id:\s*(\S+)")
_CARD_HEADER = re.compile(r"history:(claimref_[a-z]+)", re.IGNORECASE)
_CAUTION = re.compile(r"\n*Note:\s*this answer draws on graph data flagged as low-confidence[^\n]*", re.IGNORECASE)
_DECISION_WORDS = re.compile(r"\b(?:approve|deny|reject|pay out|authori[sz]e payment|is fraudulent|committed fraud|should be (?:approved|denied|paid))\b", re.IGNORECASE)


def synapt_question(question: str, claim: dict) -> str:
    """What is sent to Synapt: the masked question, plus the claim's type and, only if the narrative mentions theft, that it
    is a theft claim. The narrative itself, names, amounts and dates never leave."""
    kind = claim.get("claim_type")
    theft = bool(re.search(r"\b(?:thefts?|thie(?:f|ves)|stolen|stole|steal\w*|burglar\w*|robbed|robbery|break-?ins?|broke into)\b", claim.get("description") or "", re.IGNORECASE))
    context = f"Context: an {kind} claim" if kind == "auto" else (f"Context: a {kind} claim" if kind else "Context: an insurance claim")
    context += " involving theft." if theft else "."
    return f"{context} Question: {redact_personal_data(question).strip()}"


def confidence_label(score) -> str:
    """Synapt's own scale, from its Retrieval Pass Card documentation: 70 and above is green, 40 to 70 orange, below 40 red."""
    return "High" if isinstance(score, int | float) and score >= 0.7 else "Medium" if isinstance(score, int | float) and score >= 0.4 else "Low"


def parse_query(payload: dict, evidence_ids: set[str]) -> dict:
    """Synapt's `trident_query` answer as a part: the answer, how sure it is, the passages and procedures behind it, the graph it used."""
    answer = payload.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise SideChatError("Synapt returned no answer.", 502)
    caution = bool(_CAUTION.search(answer))
    clean = _CAUTION.sub("", answer).strip()
    chunks = []
    for chunk in (payload.get("chunks") or [])[:5]:
        if not isinstance(chunk, dict) or not isinstance(chunk.get("chunk_id"), str):
            continue
        text = str(chunk.get("text") or "")
        first = next((line.strip() for line in text.splitlines() if line.strip()), "Passage").lstrip("# ").strip() or "Passage"
        card = _CARD_HEADER.match(first)
        title = f"Historical claim card {card.group(1)}" if card else ("Historical claim card" if is_card_chunk(text) else _cap(first, 120))
        source = _CHUNK_SOURCE.search(text)
        chunks.append({
            "chunk_id": chunk["chunk_id"], "title": title, "source": source.group(1) if source else None,
            "score": round(float(chunk["score"]), 3) if isinstance(chunk.get("score"), int | float) else None,
            "in_evidence": chunk["chunk_id"] in evidence_ids,
        })
    sub = payload.get("reasoning_subgraph") or {}
    nodes = [n for n in sub.get("nodes") or [] if isinstance(n, dict)]
    by_label: dict[str, int] = {}
    for node in nodes:
        by_label[str(node.get("label"))] = by_label.get(str(node.get("label")), 0) + 1
    top = sorted(nodes, key=lambda n: -(n.get("relevance") or 0))[:6]
    graph = {
        "nodes": len(nodes), "edges": len(sub.get("edges") or []), "by_label": by_label,
        "top": [{"label": n.get("label"), "name": _cap((n.get("properties") or {}).get("name") or (n.get("properties") or {}).get("label") or "", 90), "relevance": n.get("relevance")} for n in top if (n.get("properties") or {}).get("name") or (n.get("properties") or {}).get("label")],
    }
    score = payload.get("confidence_score")
    trust = payload.get("trust_signal") or {}
    notes = []
    if caution or trust.get("degraded"):
        notes.append("Synapt marked part of the graph it used as low-confidence or incompletely connected; treat the answer with care.")
    if _DECISION_WORDS.search(clean):
        notes.append("The answer contains decision wording. This tool only supports the handler's review; it never decides a claim.")
    synapt = {
        "confidence": {"label": confidence_label(score), "overall": score, "passages": payload.get("ks_confidence"), "procedures": payload.get("ps_confidence"), "graph": payload.get("graph_confidence")},
        "trust": {"degraded": bool(trust.get("degraded")), "reasons": trust.get("reasons") or []},
        "passages": chunks, "procedures": [p for p in payload.get("procedures") or [] if isinstance(p, str)][:6], "graph": graph,
        "query_id": payload.get("query_id") if isinstance(payload.get("query_id"), str) else None,
        "returned_task_id": payload.get("task_id") if isinstance(payload.get("task_id"), str) else None,
        "stores": [s for s in payload.get("stores_used") or [] if isinstance(s, str)],
        "latency_ms": (payload.get("seed_latency_ms") or 0) + (payload.get("retrieval_latency_ms") or 0) or None,
        "warnings": [w for w in payload.get("warnings") or [] if isinstance(w, str)][:3],
    }
    return _part(
        "synapt", "From Synapt's knowledge base", text=clean, notes=notes, synapt=synapt,
        cites=[c["chunk_id"] for c in chunks if c["in_evidence"]],
    )


# ----- the service --------------------------------------------------------------------------------------------------


class RateLimiter:
    """At most `limit` questions per person per minute; the provider records every handling question it answers."""

    def __init__(self, limit=MAX_PER_MINUTE, window=60.0):
        self.limit, self.window, self._seen = limit, window, {}
        self._lock = threading.Lock()

    def allow(self, who) -> bool:
        with self._lock:
            now = time.monotonic()
            hits = self._seen.setdefault(who, deque())
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


def suggestions(run: dict) -> list[dict]:
    """Questions worth asking about this run, built from what it contains. Deterministic; no model."""
    out = []
    graph = run.get("graph") or {}
    procedures = graph.get("procedures") or []
    specific = next((p for p in procedures if p.get("applies_because") in ("theft", "claim_type")), procedures[0] if procedures else None)
    gaps = [f for f in run.get("findings") or [] if f.get("kind") == "gap"]
    priority = run.get("priority") or {}
    if specific:
        out.append({"kind": "handling", "text": f"What does the “{specific['name']}” procedure say to do, step by step?"})
    if gaps:
        out.append({"kind": "handling", "text": "Which documents should I request, and in what order?"})
        out.append({"kind": "brief", "text": "What is missing from this claim?"})
    if priority.get("score") is not None:
        out.append({"kind": "brief", "text": f"Why is the handling priority {priority.get('tier')} ({priority.get('score')}/100)?"})
    if (run.get("cohort") or {}).get("available"):
        out.append({"kind": "history", "text": "How were claims like this one usually settled?"})
    claim = run.get("claim") or {}
    if claim.get("claim_amount") is not None:
        out.append({"kind": "claim", "text": "What is the claimed amount net of the deductible, and how long after the incident was it filed?"})
    if (run.get("predictions") or {}).get("available"):
        out.append({"kind": "estimates", "text": "What does the fraud-flag signal mean for this claim?"})
    out.append({"kind": "sources", "text": "Which sources back the main findings?"})
    return out[:6]


_BRAND = re.compile(r"\bSynapt(?:'s)?(?= |$)", re.IGNORECASE)


def plain_text(value):
    """The same sentence without the vendor's name, for anyone who may not see it."""
    if not isinstance(value, str):
        return value
    value = re.sub(r"\b([Tt]he) Synapt\b", r"\1 knowledge base", value)  # "The Synapt query agent": no doubled article
    return _BRAND.sub(lambda m: "The knowledge base" if m.start() == 0 else "the knowledge base", value)


def plain_part(part: dict) -> dict:
    """One part as a person who is not an administrator may see it: no vendor name, scores, query ID, stores or timings."""
    p = dict(part)
    p["title"] = "From the knowledge base" if p["source"] == "synapt" else plain_text(p["title"])
    p["notes"] = [plain_text(n) for n in p["notes"]]
    # Synapt's own answer is shown as written; our wording around an unavailable answer is not
    p["text"] = p["text"] if p["source"] == "synapt" and p["status"] == "ok" else plain_text(p["text"])
    if p.get("synapt"):
        s = dict(p["synapt"])
        s["confidence"] = {"label": s["confidence"]["label"]}
        for key in ("query_id", "task_id", "returned_task_id", "stores", "latency_ms", "trust"):
            s.pop(key, None)
        s["warnings"] = []
        s["passages"] = [{k: v for k, v in c.items() if k != "score"} for c in s["passages"]]
        p["synapt"] = s
    return p


def view_for(answer: dict, admin: bool) -> dict:
    """What a viewer may see. Everyone sees the answer and where it came from; only an administrator sees Synapt's name,
    its scores, the query ID and the tools behind it."""
    if admin:
        return answer
    shown = dict(answer)
    shown["route"] = {"intents": answer["route"]["intents"], "fallback": answer["route"].get("fallback", False)}
    shown["parts"] = [plain_part(part) for part in answer["parts"]]
    return shown


class SideChat:
    """Answers side questions about a saved run. Reads the run; its own answers go to their own table."""

    def __init__(self, store, adapter, limiter=None):
        self.store, self.adapter = store, adapter
        self.limiter = limiter or RateLimiter()

    def history(self, run_id: str) -> list[dict]:
        return [row["body"] | {"id": row["id"], "asked_at": row["asked_at"]} for row in self.store.side_questions(run_id)]

    def ask(self, run: dict, question: str, *, owner) -> dict:
        question = re.sub(r"\s+", " ", (question or "").strip())
        if len(question) < MIN_QUESTION:
            raise SideChatError("Write a question first.", 422)
        if len(question) > MAX_QUESTION:
            raise SideChatError(f"Keep the question under {MAX_QUESTION} characters.", 422)
        run_id = run["run_id"]
        shown_question = redact_personal_data(question)
        earlier = next((h for h in reversed(self.history(run_id)) if normalize(h["question"]) == normalize(shown_question)), None)
        if earlier:
            return earlier | {"repeat": True}
        if self.store.count_side_questions(run_id) >= MAX_PER_RUN:
            raise SideChatError(f"This case has reached its limit of {MAX_PER_RUN} side questions.", 429)
        if not self.limiter.allow(owner):
            raise SideChatError("Slow down a little: too many side questions in a minute. Try again shortly.", 429)
        started = time.perf_counter()
        decided = route(question)
        parts = [OFFLINE[i](run, normalize(question)) for i in decided["intents"] if i in OFFLINE]
        if "handling" in decided["intents"]:
            parts.append(self._synapt(run, question))
        if not parts:
            parts = [answer_unknown(run, normalize(question))]
        answer = {
            "question": shown_question, "route": decided, "parts": parts,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "notice": "Side chat: not added to the brief and not used by the investigation.",
            "repeat": False,
        }
        if any(p["source"] == "synapt" and p["status"] == "unavailable" for p in parts):
            # Not saved: a saved answer would be returned for the same question forever, and Synapt recorded nothing.
            return answer | {"id": None, "asked_at": None}
        stored = self.store.add_side_question(run_id, owner, shown_question, answer)
        self.store.event(run_id, "side_question", {"question": _cap(shown_question, 300), "intents": decided["intents"], "sources": [p["source"] for p in parts], "side_question_id": stored["id"]})
        return answer | {"id": stored["id"], "asked_at": stored["asked_at"]}

    def _synapt(self, run: dict, question: str) -> dict:
        ask = getattr(self.adapter, "ask", None)
        if ask is None:
            return _part("synapt", "From Synapt's knowledge base", status="unavailable", text="Synapt is not connected in this environment, so handling questions cannot be answered here.")
        evidence_ids = {e.get("source_id") for e in run.get("evidence") or []}
        try:
            payload = ask(synapt_question(question, run.get("claim") or {}), task_id=run.get("run_id"))
            return parse_query(payload, evidence_ids)
        except SideChatError:
            return _part("synapt", "From Synapt's knowledge base", status="unavailable", text="Synapt answered without usable text. Nothing was added to the brief; try rephrasing.")
        except Exception as error:  # noqa: BLE001 - provider errors never expose their internals
            return _part("synapt", "From Synapt's knowledge base", status="unavailable", text="Synapt could not answer this right now" + (" (it timed out)." if "timeout" in type(error).__name__.lower() else ". Try again in a moment."))
