"""Synapt knowledge-graph lookup for one claim: handling procedures found by meaning, walked step by step, with sources.

Passage retrieval (`trident_get_chunks`) reads only the vector index. This module uses the graph itself:

1. `trident_search(node_type="Procedure")` finds procedure nodes by meaning.
2. An applicability check on the claim type (ours, not Synapt's) keeps the procedures that fit. It exists because the
   search ranks the nine near-identical procedures by wording, not by claim type: for an auto claim the business-loss
   procedure scored above the auto one when measured.
3. `trident_traverse(edge_types="HAS_STEP,PRECEDES,REFERENCES")` walks each kept procedure to its ordered steps and to
   the rules, controls and tasks those steps reference.
4. Every node lists the passages it was extracted from (`source_chunk_ids`). Those are the chunk IDs the passage
   evidence is cited by, so a graph procedure is citable and its text is Synapt's extraction, never ours.

Read-only: no episode is written. The functions here are pure so they can be tested without a network.
"""

import json
import re

from claims.core.schemas import ClaimInput

EDGE_TYPES = "HAS_STEP,PRECEDES,REFERENCES"
SEARCH_TOP_K = 15  # the procedures are worded alike, so a type or condition can rank below several others; applies() filters
MAX_SPECIFIC = 8  # procedures for the claim type, for theft, or for a condition the claim meets
MAX_GENERAL = 3  # procedures that name no claim type (document tracking, human review, coverage boundary)
MAX_ENTITIES = 4
MAX_STEPS = 12
MAX_RESULT_CHARS = 500_000
PROCEDURE_ID_PREFIX = "graph:procedure:"

# Claim types and the words a procedure uses for them. "home" and "property" share procedures.
_TYPE_GROUP = {
    "auto": "auto",
    "home": "home_property",
    "property": "home_property",
    "renters": "renters",
    "business": "business",
}
_GROUP_WORDS = {
    "auto": {"auto", "vehicle", "car"},
    "home_property": {"home", "property"},
    "renters": {"renters", "renter"},
    "business": {"business"},
}
_THEFT_WORDS = {"theft", "police"}
_THEFT_CLAIM = re.compile(
    r"\b(?:thefts?|thie(?:f|ves)|stolen|stole|steal\w*|burglar\w*|robbed|robbery|break-?ins?|broke into)\b",
    re.IGNORECASE,
)
_WORD = re.compile(r"[a-z]+")


class GraphError(ValueError):
    """The graph tools returned something this module does not understand."""


def claim_group(claim: ClaimInput) -> str | None:
    kind = claim.claim_type.value if claim.claim_type else None
    return _TYPE_GROUP.get(kind) if kind else None


def theft_cue(claim: ClaimInput) -> bool:
    """True when the narrative mentions theft. Used only to decide which fixed query to send, never sent itself."""
    return bool(_THEFT_CLAIM.search(claim.description or ""))


# Conditions a procedure can state about the claim itself ("filed more than 30 days after the incident", "$50,000 or more").
# The thresholds are the ones this application already uses to point a claim out (the intake's margin notes and the priority
# rule), not insurer rules, and the procedures say so. Whether a claim meets one is worked out here, from structured fields
# (and, for water damage and theft, a keyword check on the narrative that is never sent anywhere).
LATE_FILING_DAYS = 30
LARGE_LOSS_USD = 50_000
REPEAT_CLAIMS = 3
NEW_POLICY_YEARS = 1

# What a procedure's name or intent says when it applies only under a condition.
_CUE_TEXT = {
    "late_filing": re.compile(r"late-?\s?filed|filed more than 30 days|late filing|late reporting", re.IGNORECASE),
    "large_loss": re.compile(r"large[- ]loss|\$50,000", re.IGNORECASE),
    "repeat_claimant": re.compile(r"repeat claimant|three or more earlier claims|frequent claimant", re.IGNORECASE),
    "new_policyholder": re.compile(r"new policyholder|in force for less than a year", re.IGNORECASE),
    "fraud_signal": re.compile(r"fraud[- ]flag|fraud review signal", re.IGNORECASE),
    "water_damage": re.compile(r"water damage|burst pipe|\bleaks?\b", re.IGNORECASE),
}
# Water damage is a water word, or a plumbing word together with something that happened to it. "Copper pipes stripped from a
# rental" names a pipe and no water event, so it is not water damage (it used to match on "pipes" alone).
_WATER_CLAIM = re.compile(
    r"\b(?:water|leak\w*|flood\w*|overflow\w*|sewage|sewer\w*|soaked|seep\w*|waterlogged)\b",
    re.IGNORECASE,
)
_PLUMBING = re.compile(
    r"\b(?:pipes?|plumb\w*|hose|supply line|drain\w*|dishwasher|washing machine|water heater|toilet|faucet|sprinkler\w*)\b",
    re.IGNORECASE,
)
_PLUMBING_EVENT = re.compile(
    r"\b(?:burst|bursting|broke|broken|rupture\w*|froze|frozen|failed|failure|cracked|clog\w*|backed up|backing up)\b",
    re.IGNORECASE,
)


def water_cue(text: str) -> bool:
    """True when the narrative describes water damage: a water word, or a plumbing word with a failure."""
    return bool(_WATER_CLAIM.search(text) or (_PLUMBING.search(text) and _PLUMBING_EVENT.search(text)))
CUE_LABELS = {
    "theft": "The narrative mentions theft",
    "water_damage": "The narrative mentions water damage",
    "late_filing": f"Filed more than {LATE_FILING_DAYS} days after the incident",
    "large_loss": f"Claimed amount of ${LARGE_LOSS_USD:,} or more",
    "repeat_claimant": f"{REPEAT_CLAIMS} or more earlier claims",
    "new_policyholder": "Policy in force for less than a year",
}
# One fixed search per condition the claim meets. The fraud-flag signal is worked out after retrieval, so it is never a cue here.
_CUE_QUERIES = {
    "water_damage": "Synthetic home water damage documentation procedure: burst pipe or leak",
    "late_filing": "Synthetic late-filed claim review procedure: claim filed more than 30 days after the incident",
    "large_loss": "Synthetic large loss escalation procedure: claimed amount of $50,000 or more",
    "repeat_claimant": "Synthetic repeat claimant history review procedure: three or more earlier claims",
    "new_policyholder": "Synthetic new policyholder verification procedure: policy in force for less than a year",
}


def active_cues(claim: ClaimInput) -> list[str]:
    """The conditions this claim meets, in a fixed order."""
    found = []
    if theft_cue(claim):
        found.append("theft")
    if water_cue(claim.description or ""):
        found.append("water_damage")
    try:
        delay = (claim.claim_filed_date - claim.incident_date).days
    except (TypeError, AttributeError):
        delay = None
    if delay is not None and delay > LATE_FILING_DAYS:
        found.append("late_filing")
    if isinstance(claim.claim_amount, int | float) and claim.claim_amount >= LARGE_LOSS_USD:
        found.append("large_loss")
    if isinstance(claim.previous_claims_count, int) and claim.previous_claims_count >= REPEAT_CLAIMS:
        found.append("repeat_claimant")
    if isinstance(claim.policyholder_tenure_years, int | float) and claim.policyholder_tenure_years < NEW_POLICY_YEARS:
        found.append("new_policyholder")
    return found


def cue_summary(claim: ClaimInput) -> list[dict]:
    """The conditions this claim meets, with the words the page shows for them."""
    return [{"key": key, "label": CUE_LABELS[key]} for key in active_cues(claim)]


def search_plan(claim: ClaimInput) -> list[dict]:
    """The graph searches for this claim. The text is fixed vocabulary plus the claim type, never the narrative."""
    plan = []
    kind = claim.claim_type.value if claim.claim_type else None
    if kind:
        plan.append({
            "scope": "claim_type",
            "query": f"Synthetic {kind} claim documentation procedure: required evidence and handling steps",
        })
    cues = active_cues(claim)
    if "theft" in cues:
        plan.append({"scope": "theft", "query": "Synthetic theft claim: request a police report when applicable"})
    for key, query in _CUE_QUERIES.items():
        if key in cues:
            plan.append({"scope": key, "query": query})
    plan.append({
        "scope": "general",
        "query": "Document tracking and human claims handler review before any coverage decision",
    })
    return plan


def applies(search_text: str, claim: ClaimInput) -> str | None:
    """Why a procedure fits this claim, or None when it does not.

    The procedure's name and intent decide. One that states a condition (late filing, a large loss, repeat claims, a new
    policy, water damage) fits only a claim that meets it. One with theft in its name fits only a claim whose narrative
    mentions theft. One that names a claim type fits that type and no other. One that names none is general handling.
    The reason is a cue name, 'theft', 'claim_type' or 'general'.
    """
    name, _, _ = search_text.partition(": ")
    text = search_text.lower()
    words = set(_WORD.findall(text))
    named = {group for group, vocabulary in _GROUP_WORDS.items() if words & vocabulary}
    right_type = not named or claim_group(claim) in named
    if "no theft" in text and theft_cue(claim):
        return None
    conditions = [key for key, pattern in _CUE_TEXT.items() if pattern.search(search_text)]
    if conditions:
        met = set(active_cues(claim))
        return conditions[0] if right_type and all(key in met for key in conditions) else None
    if set(_WORD.findall(name.lower())) & _THEFT_WORDS:
        return "theft" if theft_cue(claim) and right_type else None
    if named:
        return "claim_type" if right_type else None
    return "general"


def decode(result, redact=lambda value: value) -> list | dict:
    """The payload of an MCP result: structured content, or JSON text, with one `{"result": "<json>"}` wrapper removed."""
    if getattr(result, "isError", False):
        raise GraphError("Synapt reported an error for a graph tool.")
    payload = getattr(result, "structuredContent", None)
    if payload is None:
        blocks = [block.text for block in result.content if block.type == "text"]
        if len(blocks) != 1 or len(blocks[0]) > MAX_RESULT_CHARS:
            raise GraphError("Synapt returned a graph response with an unsupported shape.")
        try:
            payload = json.loads(blocks[0])
        except (TypeError, ValueError):
            raise GraphError("Synapt returned a graph response that is not JSON.") from None
    if isinstance(payload, dict) and isinstance(payload.get("result"), str):
        if len(payload["result"]) > MAX_RESULT_CHARS:
            raise GraphError("Synapt returned a graph response above the size limit.")
        try:
            payload = json.loads(payload["result"])
        except (TypeError, ValueError):
            raise GraphError("Synapt returned a graph response that is not JSON.") from None
    if not isinstance(payload, list | dict):
        raise GraphError("Synapt returned a graph response with an unsupported shape.")
    return redact(payload)


def item_count(payload) -> int | None:
    """How many items a decoded Synapt response holds (passages, procedures, nodes); None when it is not a list shape."""
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("chunks", "procedures", "nodes", "results"):
            if isinstance(payload.get(key), list):
                return len(payload[key])
    return None


def parse_search(payload) -> list[dict]:
    """Procedure hits: node id, name, intent, score."""
    items = payload.get("results", payload.get("nodes")) if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise GraphError("The graph search did not return a list of nodes.")
    hits = []
    for item in items:
        if not isinstance(item, dict) or item.get("node_type", "Procedure") != "Procedure":
            continue
        node_id, text = item.get("node_id"), item.get("text")
        if not isinstance(node_id, str) or not node_id or not isinstance(text, str) or not text.strip():
            continue
        name, _, intent = text.partition(": ")
        score = item.get("score")
        hits.append({
            "node_id": node_id,
            "name": name.strip(),
            "intent": intent.strip(),
            "search_text": text.strip(),
            "score": round(float(score), 3) if isinstance(score, int | float) else None,
        })
    return hits


def _text(value, limit=600) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _chunk_ids(props: dict) -> list[str]:
    ids = props.get("source_chunk_ids")
    return [i for i in ids if isinstance(i, str) and i] if isinstance(ids, list) else []


def parse_walk(payload) -> dict:
    """Ordered steps, referenced entities and source passages of one walked procedure."""
    if not isinstance(payload, dict) or not isinstance(payload.get("nodes"), list):
        raise GraphError("The graph walk did not return nodes.")
    start = payload.get("start_node") if isinstance(payload.get("start_node"), dict) else {}
    start_props = start.get("properties") if isinstance(start.get("properties"), dict) else {}
    steps, entities = [], {}
    for node in payload["nodes"]:
        if not isinstance(node, dict) or not isinstance(node.get("properties"), dict):
            continue
        props = node["properties"]
        if node.get("label") == "Step" and _text(props.get("description")):
            number = props.get("step_number")
            steps.append({
                "number": int(number) if isinstance(number, int | float) else len(steps) + 1,
                "text": _text(props.get("description")),
                "needs": _text(props.get("pre_requisite")) or None,
                "who": _text(props.get("responsibilities")) or _text(props.get("responsible")) or None,
            })
        elif node.get("label") == "Entity" and _text(props.get("label")):
            confidence = props.get("confidence")
            entities.setdefault(_text(props.get("label"), 200), {
                "label": _text(props.get("label"), 200),
                "kind": _text(props.get("entity_type"), 60) or "Entity",
                "description": _text(props.get("description"), 400),
                "confidence": round(float(confidence), 2) if isinstance(confidence, int | float) else None,
                "chunk_ids": _chunk_ids(props),
            })
    steps.sort(key=lambda step: step["number"])
    ranked = sorted(entities.values(), key=lambda e: -(e["confidence"] or 0))[:MAX_ENTITIES]
    edge_counts: dict[str, int] = {}
    for edge in payload.get("edges") or []:
        if isinstance(edge, dict) and isinstance(edge.get("type"), str):
            edge_counts[edge["type"]] = edge_counts.get(edge["type"], 0) + 1
    chunk_ids = _chunk_ids(start_props)
    return {
        "procedure_id": _text(start_props.get("procedure_id"), 80) or None,
        "steps": steps[:MAX_STEPS],
        "entities": ranked,
        "chunk_ids": chunk_ids,
        "edge_counts": edge_counts,
    }


def procedure_record(hit: dict, walk: dict, reason: str) -> dict | None:
    """One procedure for the page and for the evidence list; None when the graph holds no steps for it."""
    if not walk["steps"]:
        return None
    identity = walk["procedure_id"] or hit["node_id"]
    return {
        "source_id": PROCEDURE_ID_PREFIX + identity,
        "node_id": hit["node_id"],
        "name": hit["name"],
        "intent": hit["intent"],
        "score": hit["score"],
        "applies_because": reason,
        "steps": walk["steps"],
        "entities": [{k: v for k, v in e.items() if k != "chunk_ids"} for e in walk["entities"]],
        "source_chunk_ids": walk["chunk_ids"],
        "edge_counts": walk["edge_counts"],
    }


def select(hits_by_scope: list[tuple[str, list[dict]]], claim: ClaimInput) -> list[tuple[dict, str]]:
    """Distinct procedures that fit the claim: type- and theft-specific first, then general handling, best score first."""
    specific, general, seen = [], [], set()
    for _scope, hits in hits_by_scope:
        for hit in hits:
            if hit["node_id"] in seen:
                continue
            reason = applies(hit["search_text"], claim)
            if reason is None:
                continue
            seen.add(hit["node_id"])
            (general if reason == "general" else specific).append((hit, reason))
    rank = lambda pair: -(pair[0]["score"] or 0)
    return sorted(specific, key=rank)[:MAX_SPECIFIC] + sorted(general, key=rank)[:MAX_GENERAL]


def backed_passages(records: list[dict]) -> set[str]:
    """The passages (chunk IDs) that a procedure chosen for this claim's type or conditions was extracted from.

    The passage search asks one question per claim type, and every "Synthetic … documentation procedure" is close to it, so it
    returns other claim types' procedures too (measured 13 October 2026: precision@5 0.35; docs/RETRIEVAL_METRICS_2026-10-13.md).
    The graph decides per procedure whether it fits the claim. A passage behind a fitting, claim-specific procedure is the source
    text of something the claim needs; general handling reaches the brief through its graph procedure."""
    return {chunk for record in records if record.get("applies_because") != "general" for chunk in record.get("source_chunk_ids") or []}


def search_summary(scope: str, query: str, hits: list[dict], chosen_ids: set[str], claim: ClaimInput) -> dict:
    """What one search found and what became of each hit, so a reader can see why a procedure was not used."""
    found = []
    for hit in hits:
        reason = applies(hit["search_text"], claim)
        found.append({
            "name": hit["name"],
            "score": hit["score"],
            "used": hit["node_id"] in chosen_ids,
            "applies_because": reason,  # None: the procedure is for another claim type, or for theft the claim does not mention
        })
    return {"scope": scope, "query": query, "found": found}


def evidence_text(record: dict) -> str:
    """The graph procedure as a cited source: Synapt's extracted steps and links, with the passages they came from."""
    lines = [f"Procedure in the Synapt knowledge graph: {record['name']}"]
    if record["intent"]:
        lines.append(f"Intent: {record['intent']}")
    lines.append("Steps, in order:")
    for step in record["steps"]:
        extra = "; ".join(
            part for part in (f"needs: {step['needs']}" if step["needs"] else "", f"by: {step['who']}" if step["who"] else "") if part
        )
        lines.append(f"{step['number']}. {step['text']}" + (f" ({extra})" if extra else ""))
    if record["entities"]:
        lines.append("Linked in the graph:")
        lines += [
            f"- {e['label']} ({e['kind']})" + (f": {e['description']}" if e["description"] else "")
            for e in record["entities"]
        ]
    if record["source_chunk_ids"]:
        lines.append("Extracted from passage(s): " + ", ".join(record["source_chunk_ids"]))
    return "\n".join(lines)


def evidence_item(record: dict, provider_id: str | None) -> dict:
    return {
        "source_id": record["source_id"],
        "title": f"Knowledge graph procedure: {record['name']}",
        "text": evidence_text(record),
        "provenance": "synapt",
        "provider_id": provider_id,
    }


def context(records: list[dict], searches: list[dict], calls: int, provider_id: str | None, cues: list[dict] | None = None) -> dict:
    return {
        "available": True,
        "provider_id": provider_id,
        "procedures": records,
        "searches": searches,
        "calls": calls,
        "cues": cues or [],
        "tools": ["trident_search", "trident_traverse"],
        "edge_types": EDGE_TYPES.split(","),
    }


def unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason, "procedures": [], "searches": [], "calls": 0}
