"""The Synapt knowledge graph is read for every investigation: search by meaning, check the claim type, walk, cite.

The payload shapes below are copied from the live tenant (12 October 2026): `trident_search` returns a list of
`{node_id, node_type, text, score}`; `trident_traverse` returns `{nodes, edges, start_node}` where the start node
carries `source_chunk_ids`, the chunk IDs the passage evidence is cited by.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from mcp.types import CallToolResult, TextContent, Tool
from test_cohort import SynaptDown, SynaptUp, build_source, spans_of, workflow_claim

from claims.api.main import create_app
from claims.core.schemas import ClaimInput, Evidence, RetrievalBundle
from claims.core.settings import Settings
from claims.synapt import knowledge_graph as kg
from claims.synapt.adapter import LiveSynaptAdapter, SynaptError

AUTO_PROCEDURE = "Incident statement and repair estimate request: Request the documents needed for an auto claim and confirm their relevance with the handler."
BUSINESS_PROCEDURE = "Synthetic business loss documentation procedure: Request and evaluate business-loss evidence for a claim."
PROPERTY_PROCEDURE = "Synthetic Property and Renters Documentation Procedure: To request the appropriate supporting documentation for home or property claims and renters claims."
POLICE_PROCEDURE = "Police report request: Request a police report for theft claims when applicable."
REVIEW_PROCEDURE = "Human claims handler review: Ensure a human claims handler reviews the evidence and applicable policy terms."
NARRATIVE = "Thieves took the car from my driveway and I saw them leave towards the highway."


def claim(kind="auto", description="Rear-end collision at a traffic light."):
    return ClaimInput(
        description=description, claim_type=kind, state="CA", incident_date="2026-01-01", claim_filed_date="2026-01-02",
        claim_amount=5000, deductible=500, previous_claims_count=0, policyholder_tenure_years=3,
    )


def hit(node_id, text, score):
    name, _, intent = text.partition(": ")
    return {"node_id": node_id, "name": name, "intent": intent, "search_text": text, "score": score}


# ----- applicability: our rule, applied to the graph's own procedure text ---------------------------


@pytest.mark.parametrize(
    ("kind", "text", "expected"),
    [
        ("auto", AUTO_PROCEDURE, "claim_type"),
        ("auto", BUSINESS_PROCEDURE, None),  # measured: the search ranks this above the auto procedure for an auto claim
        ("auto", PROPERTY_PROCEDURE, None),
        ("business", BUSINESS_PROCEDURE, "claim_type"),
        ("home", PROPERTY_PROCEDURE, "claim_type"),
        ("property", PROPERTY_PROCEDURE, "claim_type"),
        ("renters", PROPERTY_PROCEDURE, "claim_type"),
        ("renters", AUTO_PROCEDURE, None),
        ("auto", REVIEW_PROCEDURE, "general"),
        ("business", REVIEW_PROCEDURE, "general"),
    ],
)
def test_a_procedure_for_another_claim_type_is_dropped_and_general_handling_is_kept(kind, text, expected):
    assert kg.applies(text, claim(kind)) == expected


def test_a_theft_procedure_needs_a_theft_cue_in_the_claim():
    assert kg.applies(POLICE_PROCEDURE, claim("auto", "Rear-end collision.")) is None
    assert kg.applies(POLICE_PROCEDURE, claim("auto", NARRATIVE)) == "theft"
    assert kg.applies(POLICE_PROCEDURE, claim("home", "My TV was stolen during a break-in.")) == "theft"


def test_a_claim_without_a_type_gets_only_general_handling():
    no_type = ClaimInput(
        description="Damage to the insured item.", state="CA", incident_date="2026-01-01", claim_filed_date="2026-01-02",
        claim_amount=1000, deductible=100, previous_claims_count=0, policyholder_tenure_years=1,
    )
    assert kg.applies(AUTO_PROCEDURE, no_type) is None
    assert kg.applies(REVIEW_PROCEDURE, no_type) == "general"
    assert [step["scope"] for step in kg.search_plan(no_type)] == ["general"]


def test_the_search_text_is_fixed_vocabulary_and_never_the_claimants_narrative():
    plan = kg.search_plan(claim("auto", NARRATIVE))
    assert [step["scope"] for step in plan] == ["claim_type", "theft", "general"]
    joined = " ".join(step["query"] for step in plan).lower()
    for word in ("driveway", "highway", "thieves", "saw"):
        assert word not in joined
    assert "theft" not in " ".join(step["query"] for step in kg.search_plan(claim("auto"))).lower()


def test_selection_takes_specific_procedures_first_then_general_each_by_score_without_duplicates():
    found = [
        ("claim_type", [hit("n1", BUSINESS_PROCEDURE, 0.88), hit("n2", AUTO_PROCEDURE, 0.87), hit("n5", REVIEW_PROCEDURE, 0.90)]),
        ("theft", [hit("n3", POLICE_PROCEDURE, 0.93), hit("n2", AUTO_PROCEDURE, 0.87)]),
        ("general", [hit("n5", REVIEW_PROCEDURE, 0.90), hit("n6", "Document tracking: Record which documents were provided.", 0.80)]),
    ]
    chosen = kg.select(found, claim("auto", NARRATIVE))
    assert [(h["node_id"], reason) for h, reason in chosen] == [
        ("n3", "theft"), ("n2", "claim_type"), ("n5", "general"), ("n6", "general"),
    ]


# ----- reading Synapt's payloads --------------------------------------------------------------------

WALK = {
    "start_node": {
        "id": "4:x:1", "label": "Procedure",
        "properties": {"name": "Police report request", "procedure_id": "145aa149", "source_chunk_ids": ["chunk_bff73f13"]},
    },
    "nodes": [
        {"id": "s2", "label": "Step", "properties": {"step_number": 2, "description": "Confirm the relevance of the police report with the handler.", "pre_requisite": "The police report has been requested.", "responsibilities": "Claims support or intake staff in coordination with the claims handler", "responsible": ""}},
        {"id": "s1", "label": "Step", "properties": {"step_number": 1, "description": "Request a police report when the claim involves theft.", "pre_requisite": "A theft claim has been identified.", "responsibilities": "Claims support or intake staff", "responsible": ""}},
        {"id": "e1", "label": "Entity", "properties": {"label": "Human claims handler review", "entity_type": "Workflow", "description": "A required human review step.", "confidence": 0.97, "source_chunk_ids": ["chunk_bff73f13"]}},
        {"id": "e2", "label": "Entity", "properties": {"label": "Low confidence thing", "entity_type": "Task", "description": "", "confidence": 0.2, "source_chunk_ids": []}},
        {"id": "e3", "label": "Entity", "properties": {"label": "Human claims handler review", "entity_type": "Workflow", "description": "duplicate", "confidence": 0.5}},
        {"id": "c1", "label": "Chunk", "properties": {"chunk_id": "chunk_bff73f13"}},
    ],
    "edges": [
        {"source": "p", "target": "s1", "type": "HAS_STEP"}, {"source": "p", "target": "s2", "type": "HAS_STEP"},
        {"source": "s1", "target": "s2", "type": "PRECEDES"}, {"source": "s1", "target": "e1", "type": "REFERENCES"},
    ],
}


def test_the_walk_returns_steps_in_order_ranked_entities_and_the_source_passages():
    walk = kg.parse_walk(WALK)
    assert [s["number"] for s in walk["steps"]] == [1, 2]
    assert walk["steps"][0] == {
        "number": 1, "text": "Request a police report when the claim involves theft.",
        "needs": "A theft claim has been identified.", "who": "Claims support or intake staff",
    }
    assert [e["label"] for e in walk["entities"]] == ["Human claims handler review", "Low confidence thing"]
    assert walk["chunk_ids"] == ["chunk_bff73f13"] and walk["procedure_id"] == "145aa149"
    assert walk["edge_counts"] == {"HAS_STEP": 2, "PRECEDES": 1, "REFERENCES": 1}


def test_a_procedure_without_steps_in_the_graph_is_not_shown():
    walk = kg.parse_walk({"nodes": [], "edges": []})
    assert kg.procedure_record(hit("n", POLICE_PROCEDURE, 0.9), walk, "theft") is None


def test_the_cited_text_is_synapts_extraction_with_its_source_passages_and_nothing_added():
    record = kg.procedure_record(hit("n", POLICE_PROCEDURE, 0.934), kg.parse_walk(WALK), "theft")
    item = kg.evidence_item(record, "provider-1")
    assert item["source_id"] == "graph:procedure:145aa149" and item["provenance"] == "synapt"
    assert item["provider_id"] == "provider-1"
    text = item["text"]
    assert text.index("1. Request a police report") < text.index("2. Confirm the relevance")
    assert "(needs: A theft claim has been identified.; by: Claims support or intake staff)" in text
    assert "Human claims handler review (Workflow): A required human review step." in text
    assert text.endswith("Extracted from passage(s): chunk_bff73f13")


def test_search_results_of_other_node_types_and_malformed_rows_are_ignored():
    rows = [
        {"node_id": "a", "node_type": "Procedure", "text": POLICE_PROCEDURE, "score": 0.9},
        {"node_id": "b", "node_type": "Entity", "text": "Something: else", "score": 0.99},
        {"node_id": "", "node_type": "Procedure", "text": "No id: x", "score": 0.5},
        {"node_id": "c", "node_type": "Procedure", "text": "", "score": 0.5},
        "not a dict",
    ]
    assert [h["node_id"] for h in kg.parse_search(rows)] == ["a"]
    with pytest.raises(kg.GraphError):
        kg.parse_search({"unexpected": True})
    with pytest.raises(kg.GraphError):
        kg.parse_walk([])


def text_result(payload, wrapped=False):
    body = json.dumps({"result": json.dumps(payload)} if wrapped else payload)
    return CallToolResult(content=[TextContent(type="text", text=body)])


def test_results_are_decoded_from_text_wrapper_or_structured_content_and_errors_are_refused():
    rows = [{"node_id": "a"}]
    assert kg.decode(text_result(rows)) == rows
    assert kg.decode(text_result(rows, wrapped=True)) == rows
    assert kg.decode(CallToolResult(content=[], structuredContent={"nodes": []})) == {"nodes": []}
    with pytest.raises(kg.GraphError):
        kg.decode(CallToolResult(content=[TextContent(type="text", text="oops")], isError=True))
    with pytest.raises(kg.GraphError):
        kg.decode(CallToolResult(content=[TextContent(type="text", text="not json")]))


# ----- the adapter: read-only, provider-scoped, and every call checked against the tool schema ------


@pytest.fixture
def adapter():
    return LiveSynaptAdapter(Settings(
        _env_file=None, synapt_username="test-user", synapt_password="very-secret-password",
        synapt_provider_id="provider-1",
    ))


def tool(name, **properties):
    return Tool(name=name, inputSchema={
        "type": "object", "properties": {"provider_id": {"type": "string"}, **properties}, "required": ["provider_id"],
    })


SEARCH_TOOL = tool("trident_search", query={"type": "string"}, node_type={"type": "string"}, top_k={"type": "integer"})
TRAVERSE_TOOL = tool(
    "trident_traverse", node_id={"type": "string"}, edge_types={"type": "string"}, depth={"type": "integer"},
)

HITS = {
    "claim_type": [
        {"node_id": "n-biz", "node_type": "Procedure", "text": BUSINESS_PROCEDURE, "score": 0.882},
        {"node_id": "n-auto", "node_type": "Procedure", "text": AUTO_PROCEDURE, "score": 0.869},
    ],
    "theft": [{"node_id": "n-police", "node_type": "Procedure", "text": POLICE_PROCEDURE, "score": 0.934}],
    "general": [{"node_id": "n-review", "node_type": "Procedure", "text": REVIEW_PROCEDURE, "score": 0.907}],
}


def graph_session(monkeypatch, adapter, tools, walk=WALK):
    calls = []

    class Session:
        async def list_tools(self, cursor=None):
            return SimpleNamespace(tools=tools, nextCursor=None)

        async def call_tool(self, name, arguments):
            calls.append((name, arguments))
            if name == "trident_search":
                scope = "theft" if "theft" in arguments["query"].lower() else (
                    "general" if arguments["query"].startswith("Document tracking") else "claim_type")
                return text_result(HITS[scope])
            return text_result(walk, wrapped=True)

    @asynccontextmanager
    async def session():
        yield Session()

    monkeypatch.setattr(adapter, "_session", session)
    return calls


def test_the_graph_lookup_searches_applies_the_claim_type_and_walks_only_what_fits(monkeypatch, adapter):
    calls = graph_session(monkeypatch, adapter, [SEARCH_TOOL, TRAVERSE_TOOL])
    graph = adapter.retrieve_graph(claim("auto", NARRATIVE))
    assert graph["available"] is True and graph["calls"] == len(calls)
    names = [c[0] for c in calls]
    assert set(names) == {"trident_search", "trident_traverse"} and names.count("trident_search") == 3
    walked = [c[1]["node_id"] for c in calls if c[0] == "trident_traverse"]
    assert walked == ["n-police", "n-auto", "n-review"]  # the business-loss procedure scored higher and was not walked
    assert all(c[1]["provider_id"] == "provider-1" for c in calls)
    assert all(c[1]["edge_types"] == "HAS_STEP,PRECEDES,REFERENCES" for c in calls if c[0] == "trident_traverse")
    assert NARRATIVE not in json.dumps(calls) and "driveway" not in json.dumps(calls)
    assert [p["applies_because"] for p in graph["procedures"]] == ["theft", "claim_type", "general"]
    skipped = [f for s in graph["searches"] for f in s["found"] if not f["used"]]
    assert [(f["name"][:18], f["applies_because"]) for f in skipped] == [("Synthetic business", None)]


def test_the_lookup_never_calls_a_write_or_episode_tool(monkeypatch, adapter):
    calls = graph_session(monkeypatch, adapter, [SEARCH_TOOL, TRAVERSE_TOOL, tool("trident_query"), tool("trident_ingest")])
    adapter.retrieve_graph(claim("business"))
    assert {c[0] for c in calls} <= {"trident_search", "trident_traverse"}


def test_a_provider_that_lacks_the_graph_tools_fails_closed(monkeypatch, adapter):
    graph_session(monkeypatch, adapter, [SEARCH_TOOL])
    with pytest.raises(SynaptError, match="knowledge-graph tools"):
        adapter.retrieve_graph(claim())


def test_a_tool_whose_schema_cannot_take_our_arguments_is_refused(monkeypatch, adapter):
    graph_session(monkeypatch, adapter, [tool("trident_search", query={"type": "string"}), TRAVERSE_TOOL])
    with pytest.raises(SynaptError):
        adapter.retrieve_graph(claim())


def test_a_malformed_response_is_a_synapt_error_not_a_crash(monkeypatch, adapter):
    graph_session(monkeypatch, adapter, [SEARCH_TOOL, TRAVERSE_TOOL], walk=["not", "a", "walk"])
    with pytest.raises(SynaptError):
        adapter.retrieve_graph(claim())


# ----- the investigation: graph procedures are cited evidence, and a failure is reported -----------


class GraphUp(SynaptUp):
    def retrieve_graph(self, claim):
        record = kg.procedure_record(hit("n", POLICE_PROCEDURE, 0.9), kg.parse_walk(WALK), "theft")
        return kg.context([record], [], 3, "provider-1")


class GraphFails(SynaptUp):
    def retrieve_graph(self, claim):
        raise SynaptError("graph unreachable")


@pytest.fixture
def workflow_settings(tmp_path):
    source_path = tmp_path / "source.parquet"
    build_source(source_path)
    return Settings(
        _env_file=None, claims_database_path=tmp_path / "runtime.sqlite", claims_data_path=tmp_path / "absent.json",
        claims_artifact_dir=tmp_path / "models", claims_parquet_path=source_path,
    )


def investigate(settings, adapter):
    app = create_app(settings, adapter=adapter)
    with TestClient(app) as client:
        return app, client.post("/api/investigations", json={"claim": workflow_claim()}).json()


def test_graph_procedures_become_cited_synapt_evidence_and_the_run_carries_the_graph(workflow_settings):
    app, run = investigate(workflow_settings, GraphUp([]))
    item = next(e for e in run["evidence"] if e["source_id"] == "graph:procedure:145aa149")
    assert item["provenance"] == "synapt" and item["title"] == "Knowledge graph procedure: Police report request"
    assert run["graph"]["available"] is True and run["graph"]["procedures"][0]["name"] == "Police report request"
    assert next(e for e in run["evidence"] if e["source_id"] == "claim:input")  # the submitted claim is still last
    spans = spans_of(app, run["run_id"])
    graph_span = next(s for s in spans if s["name"] == "knowledge.graph")
    assert graph_span["attributes"]["procedures"] == 1


def test_a_graph_failure_is_reported_as_a_limitation_and_does_not_fail_the_run(workflow_settings):
    _, run = investigate(workflow_settings, GraphFails([]))
    assert run["graph"]["available"] is False
    assert not [e for e in run["evidence"] if e["source_id"].startswith("graph:")]
    assert any("knowledge-graph lookup failed" in f["text"] for f in run["findings"] if f["kind"] == "limitation")
    assert run["evidence"]  # passage retrieval is unaffected


def test_only_passages_behind_a_claim_specific_procedure_are_backed():
    specific = kg.procedure_record(hit("n", POLICE_PROCEDURE, 0.9), kg.parse_walk(WALK), "theft")
    general = kg.procedure_record(hit("g", "Human claims handler review: Review before any decision.", 0.8),
                                  kg.parse_walk(WALK | {"start_node": {"properties": {"source_chunk_ids": ["chunk_auto"]}}}), "general")
    assert kg.backed_passages([specific, general]) == {"chunk_bff73f13"}
    assert kg.backed_passages([general]) == set()


class TwoPassagesAndGraph(GraphUp):
    """The passage search returns the auto SOP's passage (the source of the chosen police-report procedure) and another claim
    type's passage, as the live type search does."""

    def retrieve(self, claim):
        return RetrievalBundle(mode="live", semantic_claim_ids=[], evidence=[
            Evidence(source_id="chunk_bff73f13", title="Synthetic auto documentation and theft procedure", text="For an auto claim…", provenance="synapt"),
            Evidence(source_id="chunk_business", title="Synthetic business loss documentation procedure", text="For business claims…", provenance="synapt"),
        ])


def test_passages_of_procedures_the_graph_did_not_choose_are_dropped_from_the_evidence(workflow_settings):
    app, run = investigate(workflow_settings, TwoPassagesAndGraph([]))
    ids = [e["source_id"] for e in run["evidence"]]
    assert "chunk_bff73f13" in ids and "graph:procedure:145aa149" in ids
    assert "chunk_business" not in ids
    span = next(s for s in spans_of(app, run["run_id"]) if s["name"] == "evidence.passages")
    assert span["attributes"]["dropped"] == ["chunk_business"] and span["attributes"]["kept"] == 1


def test_every_passage_stays_when_the_graph_lookup_failed(workflow_settings):
    class PassagesGraphFails(TwoPassagesAndGraph):
        def retrieve_graph(self, claim):
            raise SynaptError("graph unreachable")

    _, run = investigate(workflow_settings, PassagesGraphFails([]))
    ids = [e["source_id"] for e in run["evidence"]]
    assert "chunk_bff73f13" in ids and "chunk_business" in ids


def test_without_a_graph_capable_adapter_the_run_has_no_graph_and_no_error(workflow_settings):
    _, run = investigate(workflow_settings, SynaptUp([]))
    assert run["graph"] is None


def test_a_degraded_run_reads_no_graph_because_synapt_was_not_used(workflow_settings):
    from test_cohort import LocalCopy

    class DownWithGraph(SynaptDown):
        def retrieve_graph(self, claim):
            raise AssertionError("the graph must not be read when Synapt retrieval failed")

    app = create_app(workflow_settings, adapter=DownWithGraph(), fallback=LocalCopy([]))
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": workflow_claim()}).json()
    assert run["mode"] == "degraded" and run["graph"] is None


def test_the_interactive_case_search_does_not_read_the_graph(workflow_settings):
    class Explodes(SynaptUp):
        def retrieve_graph(self, claim):
            raise AssertionError("the interactive search must not pay for the graph")

    app = create_app(workflow_settings, adapter=Explodes([]))
    with TestClient(app) as client:
        response = client.post("/api/search", json={"claim": workflow_claim()})
    assert response.status_code == 200 and "graph" not in response.json()


# ----- procedures that apply only when a fact about the claim is true ----------------------------------------------------

LATE = "Synthetic late-filed claim review procedure: Review a claim filed more than 30 days after the incident by recording dates and obtaining an explanation."
LARGE = "Synthetic large loss escalation procedure: Escalate and document claims with a claimed amount of $50,000 or more for human review."
REPEAT = "Synthetic repeat claimant history review procedure: Review a policyholder's earlier claims history when the policyholder has three or more earlier claims."
NEWPOL = "Synthetic new policyholder verification procedure: Verify timing and documentation details when the policy has been in force for less than a year."
WATER = "Home Water Damage Documentation Procedure: Collect documentation for a home or property water damage claim."
VEHICLE_THEFT = "Synthetic vehicle theft verification procedure: Verify reported vehicle theft details for claims handling review."
COLLISION = "Synthetic auto collision documentation procedure: Document a reported auto collision or other damage to the insured vehicle when no theft is reported."
INVENTORY = "Synthetic renters belongings inventory procedure: Collect a renters claimant's belongings inventory, ownership evidence and theft-related police report information."
FRAUD = "Synthetic fraud-flag review signal procedure: Handle a fraud review signal as a statistical indicator without accusing the claimant."


def facts(kind="auto", description="Rear-end collision at a traffic light.", **over):
    base = {
        "description": description, "claim_type": kind, "state": "CA", "incident_date": "2026-01-01", "claim_filed_date": "2026-01-02",
        "claim_amount": 5000, "deductible": 500, "previous_claims_count": 0, "policyholder_tenure_years": 3,
    }
    return ClaimInput.model_validate(base | over)


@pytest.mark.parametrize(
    ("text", "meets", "misses"),
    [
        (LATE, {"claim_filed_date": "2026-02-01"}, {"claim_filed_date": "2026-01-31"}),  # 31 days is late, 30 is not
        (LARGE, {"claim_amount": 50000}, {"claim_amount": 49999.99}),
        (REPEAT, {"previous_claims_count": 3}, {"previous_claims_count": 2}),
        (NEWPOL, {"policyholder_tenure_years": 0.99}, {"policyholder_tenure_years": 1.0}),
    ],
)
def test_a_conditional_procedure_fits_only_a_claim_that_meets_its_condition_at_the_exact_threshold(text, meets, misses):
    reason = kg.applies(text, facts(**meets))
    assert reason in {"late_filing", "large_loss", "repeat_claimant", "new_policyholder"}
    assert kg.applies(text, facts(**misses)) is None
    assert kg.applies(text, facts("home", **meets)) == reason and kg.applies(text, facts("business", **meets)) == reason  # not tied to a type


@pytest.mark.parametrize(
    ("narrative", "water"),
    [
        ("A burst pipe flooded the kitchen overnight.", True),
        ("The washing machine hose burst while we were out.", True),
        ("The supply line under the sink cracked and the cabinet is ruined.", True),
        ("The sprinkler head failed and the lawn and fence are ruined.", True),
        ("The dishwasher overflowed onto the floor.", True),
        # found on 12 October: a plumbing word with no water event is not water damage
        ("Tenants moved out and I found the copper pipes stripped from my rental duplex.", False),
        ("My dishwasher and washing machine were taken from the garage.", False),
        ("A drain cover and a pipe wrench were missing from the shed.", False),
        ("Someone drained the account on the policy.", False),
        ("A kitchen fire damaged the cabinets.", False),
    ],
)
def test_water_damage_is_a_water_word_or_a_plumbing_word_with_a_failure_not_a_plumbing_word_alone(narrative, water):
    assert ("water_damage" in kg.active_cues(facts("home", narrative))) is water


def test_the_water_damage_procedure_needs_water_in_the_narrative_and_a_home_or_property_claim():
    assert kg.applies(WATER, facts("home", "A burst pipe flooded the kitchen overnight.")) == "water_damage"
    assert kg.applies(WATER, facts("property", "Water leaked through the roof into the unit.")) == "water_damage"
    assert kg.applies(WATER, facts("home", "A kitchen fire damaged the cabinets.")) is None
    assert kg.applies(WATER, facts("auto", "Car flooded in a storm.")) is None  # a home procedure never fits an auto claim
    assert kg.applies(WATER, facts("renters", "Pipe leak soaked the carpet.")) is None


def test_vehicle_theft_needs_an_auto_claim_that_mentions_theft_and_collision_needs_no_theft():
    assert kg.applies(VEHICLE_THEFT, facts("auto", NARRATIVE)) == "theft"
    assert kg.applies(VEHICLE_THEFT, facts("auto", "Rear-end collision at a traffic light.")) is None
    assert kg.applies(VEHICLE_THEFT, facts("home", "Burglars stole the television.")) is None  # theft, but a vehicle procedure
    assert kg.applies(COLLISION, facts("auto", "Rear-end collision at a traffic light.")) == "claim_type"
    assert kg.applies(COLLISION, facts("auto", NARRATIVE)) is None
    assert kg.applies(COLLISION, facts("home", "Hail damaged the roof.")) is None


def test_a_procedure_that_only_mentions_theft_in_its_intent_is_not_gated_on_it():
    assert kg.applies(INVENTORY, facts("renters", "Laptop damaged in a power surge.")) == "claim_type"
    assert kg.applies(INVENTORY, facts("auto", "Rear-end collision.")) is None


def test_the_fraud_flag_procedure_is_never_chosen_at_retrieval_because_the_signal_is_worked_out_later():
    for kind in ("auto", "home", "renters", "business"):
        assert kg.applies(FRAUD, facts(kind, NARRATIVE, previous_claims_count=9, claim_amount=900000)) is None
    assert "fraud_signal" not in kg.active_cues(facts("auto", NARRATIVE, previous_claims_count=9))


def test_the_conditions_a_claim_meets_come_back_in_a_fixed_order_with_the_words_the_page_shows():
    everything = facts(
        "home", "A burst pipe flooded the kitchen; the thieves took the television.", claim_filed_date="2026-03-01", claim_amount=75000,
        previous_claims_count=4, policyholder_tenure_years=0.5,
    )
    assert kg.active_cues(everything) == ["theft", "water_damage", "late_filing", "large_loss", "repeat_claimant", "new_policyholder"]
    assert [c["label"] for c in kg.cue_summary(everything)] == [
        "The narrative mentions theft", "The narrative mentions water damage", "Filed more than 30 days after the incident",
        "Claimed amount of $50,000 or more", "3 or more earlier claims", "Policy in force for less than a year",
    ]
    assert kg.active_cues(facts("auto")) == [] and kg.cue_summary(facts("auto")) == []


def test_each_condition_adds_one_fixed_search_and_the_narrative_never_reaches_a_query():
    narrative = "A burst pipe flooded the Willow Street kitchen; claimant Jane Doe, 555-123-4567."
    plan = kg.search_plan(facts("home", narrative, claim_filed_date="2026-03-01", claim_amount=75000, previous_claims_count=4, policyholder_tenure_years=0.5))
    assert [p["scope"] for p in plan] == ["claim_type", "water_damage", "late_filing", "large_loss", "repeat_claimant", "new_policyholder", "general"]
    joined = " ".join(p["query"] for p in plan)
    for leaked in ("Willow", "Jane", "555", "kitchen", "75000", "75,000", "2026"):
        assert leaked not in joined
    assert [p["scope"] for p in kg.search_plan(facts("auto"))] == ["claim_type", "general"]


def test_selection_keeps_up_to_eight_specific_procedures_and_three_general_ones():
    found = [("claim_type", [hit(f"s{i}", f"Synthetic auto procedure {i}: for auto claims.", 0.9 - i / 100) for i in range(12)])]
    found.append(("general", [hit(f"g{i}", f"General step {i}: handling.", 0.8 - i / 100) for i in range(6)]))
    chosen = kg.select(found, claim("auto"))
    assert [r for _, r in chosen].count("claim_type") == 8 and [r for _, r in chosen].count("general") == 3
    assert [h["node_id"] for h, r in chosen if r == "claim_type"] == [f"s{i}" for i in range(8)]  # best score first


def test_the_context_names_the_conditions_so_a_reader_can_see_why_a_procedure_is_there():
    ctx = kg.context([], [], 3, "provider-1", kg.cue_summary(facts("auto", NARRATIVE)))
    assert ctx["cues"] == [{"key": "theft", "label": "The narrative mentions theft"}]
    assert kg.context([], [], 0, "p")["cues"] == []


# ----- a call that stalls is cut off and retried, not waited out ------------------------------------------------------------


def test_a_stalled_graph_call_is_cut_off_and_the_lookup_is_retried_instead_of_waiting_it_out(monkeypatch):
    import asyncio
    import time

    adapter = LiveSynaptAdapter(Settings(
        _env_file=None, synapt_username="test-user", synapt_password="very-secret-password", synapt_provider_id="provider-1",
        synapt_fast_attempt_seconds=1, synapt_timeout_seconds=30,
    ))
    stalls = {"left": 1}

    class Session:
        async def list_tools(self, cursor=None):
            return SimpleNamespace(tools=[SEARCH_TOOL, TRAVERSE_TOOL], nextCursor=None)

        async def call_tool(self, name, arguments):
            if name == "trident_search" and stalls["left"]:
                stalls["left"] -= 1
                await asyncio.sleep(60)  # a stalled call, as Synapt returned about 2% of the time
            if name != "trident_search":
                return text_result(WALK, wrapped=True)
            scope = "theft" if "theft" in arguments["query"].lower() else (
                "general" if arguments["query"].startswith("Document tracking") else "claim_type")
            return text_result(HITS[scope])

    @asynccontextmanager
    async def session():
        yield Session()

    monkeypatch.setattr(adapter, "_session", session)
    started = time.perf_counter()
    graph = adapter.retrieve_graph(claim("auto", NARRATIVE))
    assert graph["available"] is True and graph["procedures"]
    assert time.perf_counter() - started < 10  # one second to give up on the stall, then the retry; not the 30 s deadline
    assert stalls["left"] == 0


def test_a_call_that_keeps_stalling_ends_as_a_failed_lookup_not_a_hang(monkeypatch):
    import asyncio
    import time

    adapter = LiveSynaptAdapter(Settings(
        _env_file=None, synapt_username="test-user", synapt_password="very-secret-password", synapt_provider_id="provider-1",
        synapt_fast_attempt_seconds=1, synapt_timeout_seconds=30,
    ))

    class Session:
        async def list_tools(self, cursor=None):
            return SimpleNamespace(tools=[SEARCH_TOOL, TRAVERSE_TOOL], nextCursor=None)

        async def call_tool(self, name, arguments):
            await asyncio.sleep(60)

    @asynccontextmanager
    async def session():
        yield Session()

    monkeypatch.setattr(adapter, "_session", session)
    started = time.perf_counter()
    with pytest.raises(SynaptError):
        adapter.retrieve_graph(claim("auto", NARRATIVE))
    assert time.perf_counter() - started < 15  # three attempts of one second, with their short pauses


def test_the_next_attempt_does_not_wait_for_the_stalled_one_to_close_its_session(monkeypatch):
    """Cancelling a stalled call made its session wait for the transport to give up: 19 s on 12 October, after the 8 s deadline had fired."""
    import asyncio
    import time

    adapter = LiveSynaptAdapter(Settings(
        _env_file=None, synapt_username="test-user", synapt_password="very-secret-password", synapt_provider_id="provider-1",
        synapt_fast_attempt_seconds=1, synapt_timeout_seconds=30,
    ))
    opened = {"n": 0}

    class Stalls:
        async def list_tools(self, cursor=None):
            return SimpleNamespace(tools=[SEARCH_TOOL, TRAVERSE_TOOL], nextCursor=None)

        async def call_tool(self, name, arguments):
            await asyncio.sleep(60)

    class Works(Stalls):
        async def call_tool(self, name, arguments):
            if name != "trident_search":
                return text_result(WALK, wrapped=True)
            scope = "theft" if "theft" in arguments["query"].lower() else (
                "general" if arguments["query"].startswith("Document tracking") else "claim_type")
            return text_result(HITS[scope])

    @asynccontextmanager
    async def session():
        opened["n"] += 1
        if opened["n"] == 1:
            try:
                yield Stalls()
            finally:
                await asyncio.sleep(25)  # the clean-up of a session whose request never came back
        else:
            yield Works()

    monkeypatch.setattr(adapter, "_session", session)
    started = time.perf_counter()
    graph = adapter.retrieve_graph(claim("auto", NARRATIVE))
    assert graph["available"] is True and opened["n"] == 2
    assert time.perf_counter() - started < 8  # one second for the stall, then straight on; not another 25 for the clean-up


def test_the_graph_searches_go_out_together_and_so_do_the_walks_and_the_result_keeps_its_order(monkeypatch, adapter):
    """Each call waits until all of its group are in flight: a sequential lookup would wait forever and fail."""
    import asyncio

    in_flight = {"trident_search": 0, "trident_traverse": 0}
    gates = {"trident_search": None, "trident_traverse": None}
    sizes = {"trident_search": 3, "trident_traverse": 3}
    order = []

    class Session:
        async def list_tools(self, cursor=None):
            return SimpleNamespace(tools=[SEARCH_TOOL, TRAVERSE_TOOL], nextCursor=None)

        async def call_tool(self, name, arguments):
            gates[name] = gates[name] or asyncio.Event()
            in_flight[name] += 1
            if in_flight[name] == sizes[name]:
                gates[name].set()
            await asyncio.wait_for(gates[name].wait(), 5)  # only released once the whole group has been sent
            order.append(name)
            if name == "trident_search":
                scope = "theft" if "theft" in arguments["query"].lower() else (
                    "general" if arguments["query"].startswith("Document tracking") else "claim_type")
                return text_result(HITS[scope])
            return text_result(WALK, wrapped=True)

    @asynccontextmanager
    async def session():
        yield Session()

    monkeypatch.setattr(adapter, "_session", session)
    graph = adapter.retrieve_graph(claim("auto", NARRATIVE))
    assert graph["available"] is True and graph["calls"] == 6
    assert order == ["trident_search"] * 3 + ["trident_traverse"] * 3
    # the same procedures, in the same order, as when the calls went one after another
    assert [p["applies_because"] for p in graph["procedures"]] == ["theft", "claim_type", "general"]
