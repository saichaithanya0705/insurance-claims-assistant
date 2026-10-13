"""Who does what in an investigation: the agents, their roles, what each is told and which tools each may call.

Every piece of work in an investigation is done by a named agent with a written role. An agent holds a short list of tools and
nothing else: the list is checked on every call (``claims.agents.access``), so a retrieval agent cannot walk the knowledge graph, no agent
can write to the knowledge base, and the agents that only reason over evidence hold no tools at all. The list below is the single
source for the checks, the Agents page, the traces and the documentation.

Three more actors can reach the knowledge base, none of them an investigation agent: the *operator* (connection checks and the
verification scripts, read-only), the *ingestion* job (the only one that may write documents) and the human *reviewer* (the only one
that may send feedback on an answer). They are listed so the full set of who-can-do-what is in one place.

Names, purposes and tool labels are written without the vendor's name: a person who is not an administrator sees them (see
``claims.observability.progress`` for the same rule on the live view). Tool IDs, identities and prompts are for administrators.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Tool:
    id: str
    system: str  # "synapt" or "local"
    plain: str  # what it is, in words that name no vendor
    summary: str  # a fuller line for administrators
    writes: bool = False


def _tools(*items: Tool) -> dict[str, Tool]:
    return {tool.id: tool for tool in items}


TOOLS: dict[str, Tool] = _tools(
    Tool("trident_get_chunks", "synapt", "Knowledge-base passage search", "Passages ranked by meaning from the knowledge base, each with its source ID."),
    Tool("trident_search", "synapt", "Knowledge-base search", "Search the knowledge base or its graph by meaning: passages, or procedure nodes."),
    Tool("trident_get_procedures", "synapt", "Procedure list", "List the handling procedures a provider holds (names, intents, steps)."),
    Tool("trident_traverse", "synapt", "Knowledge-graph walk", "Walk the knowledge graph from a node to its steps and source passages."),
    Tool("trident_ticket_neighbours", "synapt", "Past-claim ticket search", "The past claims in the ticket store closest to this one (the ticket-only leg of the query tool: no question, no graph walk, no model)."),
    Tool("trident_query", "synapt", "Knowledge-base question answering", "Ask the provider's own query agent a question and read its written answer (it records the question as an episode)."),
    Tool("trident_get_stats", "synapt", "Knowledge-base statistics", "Counts of what the provider holds (documents, chunks, nodes)."),
    Tool("trident_episodes", "synapt", "Question history", "The questions the provider's query agent has answered and learned from."),
    Tool("trident_get_schema", "synapt", "Graph structure", "The graph's node and edge types."),
    Tool("trident_get_node", "synapt", "Graph node lookup", "One graph node by ID."),
    Tool("trident_find_exact", "synapt", "Exact-match lookup", "Exact-match lookup in the knowledge base."),
    Tool("trident_cypher", "synapt", "Read-only graph query", "A read-only graph query written in Cypher."),
    Tool("trident_ingest", "synapt", "Add a document", "Add a document to the knowledge base.", writes=True),
    Tool("trident_feedback", "synapt", "Rate an answer", "Tell the provider whether its query agent's answer helped.", writes=True),
    Tool("history.search", "local", "Past-claims search", "Search this application's history of past claims for the closest matches."),
    Tool("cohort.statistics", "local", "Cohort figures", "Exact figures for the cohort of past claims like this one (amounts, days to close, outcomes)."),
    Tool("models.predict", "local", "Statistical models", "The trained models: settlement amount, resolution time and fraud review signal."),
    Tool("priority.score", "local", "Priority rubric", "The handling-priority rubric."),
    Tool("brief.validate", "local", "Brief checks", "The brief's fixed checks: schema, citations and action boundaries."),
)


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    kind: str  # "agent" (part of the investigation), "system" or "human"
    method: str  # "model", "rules" or "none"
    stage: str  # the workflow stage it works in, or "" for an actor outside the investigation
    purpose: str  # what it is for: the description shown to people
    tools: frozenset[str] = field(default_factory=frozenset)
    model_purpose: str = ""  # which model setting it uses ("classification", ...), for a model agent
    prompt: str = ""  # the role it is given, ahead of the shared operating rules
    cannot: str = ""  # what it is kept from doing, in plain words

    @property
    def identity(self) -> str:
        """The name this agent presents to the knowledge base, so its calls can be told apart from every other agent's."""
        return f"claims-assistant.{self.id}"


def _agent(id, name, method, stage, purpose, tools=(), model_purpose="", prompt="", cannot="", kind="agent"):
    return AgentSpec(id, name, kind, method, stage, purpose, frozenset(tools), model_purpose, prompt, cannot)


AGENTS: dict[str, AgentSpec] = {
    spec.id: spec
    for spec in (
        _agent(
            "triage",
            "Claim Triage Agent",
            "model",
            "classify",
            "Reads the submitted claim and decides which insurance line it belongs to (auto, home, renters, property or business), "
            "and says when the category itself is unclear.",
            model_purpose="classification",
            prompt=(
                "You are the Claim Triage Agent on an insurance claims-handling team. Your only job is to decide which insurance "
                "line a newly submitted claim belongs to. You see the claim as submitted and hold no tools. The agents after you "
                "gather and assess the evidence."
            ),
            cannot="Hold any tool. It cannot search the knowledge base or the claims history.",
        ),
        _agent(
            "passage_retriever",
            "Policy Passage Retriever",
            "model",
            "retrieve",
            "Fetches the policy and procedure passages that apply to this kind of claim from the knowledge base, and the "
            "past claims in its ticket store closest to this claim. Its standard searches always run; a model may then search for "
            "what they missed and keep what the claim needs. Read-only.",
            tools=("trident_get_chunks", "trident_search", "trident_get_procedures", "trident_ticket_neighbours"),
            model_purpose="retrieval",
            prompt=(
                "You are the Policy Passage Retriever on an insurance claims-handling team. You find the policy and procedure "
                "passages that apply to a claim. You can search and read the knowledge base's passages and nothing else: you "
                "cannot write to it or ask it anything outside your tools."
            ),
            cannot="Walk the graph, ask the knowledge base's query agent, or write anything to the knowledge base.",
        ),
        _agent(
            "graph_navigator",
            "Procedure Graph Navigator",
            "model",
            "retrieve",
            "Reads handling procedures from the knowledge graph: finds the procedures that fit the claim, then walks each one "
            "step by step to the passages it came from. Its standard searches always run; a model may then look for a kind of "
            "procedure they missed, and every procedure still has to fit the claim. Read-only.",
            tools=("trident_search", "trident_traverse"),
            model_purpose="retrieval",
            prompt=(
                "You are the Procedure Graph Navigator on an insurance claims-handling team. You find the handling procedures "
                "that apply to a claim by searching the knowledge graph and reading procedures step by step. You can read the "
                "graph and nothing else: you cannot write to it."
            ),
            cannot="Fetch passages directly, ask the knowledge base's query agent, or write anything to the knowledge base.",
        ),
        _agent(
            "knowledge_qa",
            "Knowledge Q&A Agent",
            "model",
            "retrieve",
            "Asks the knowledge base's own query agent one handling question about the claim, written by a model from the claim's "
            "type and conditions only, and shows its written answer beside the brief. The answer is for the handler to read: it is "
            "never used as evidence.",
            tools=("trident_query",),
            model_purpose="retrieval",
            prompt=(
                "You are the Knowledge Q&A Agent on an insurance claims-handling team. You put one handling question to the "
                "knowledge base's own query agent. You can ask that one question and nothing else."
            ),
            cannot="Search passages or the graph, or write anything to the knowledge base.",
        ),
        _agent(
            "history_analyst",
            "Claims History Analyst",
            "rules",
            "retrieve",
            "Searches this application's own history of past claims for the closest matches and works out exact cohort figures "
            "(typical amounts, days to close, outcomes). It reads our data, not the knowledge base.",
            tools=("history.search", "cohort.statistics"),
            cannot="Call any knowledge-base tool.",
        ),
        _agent(
            "investigator",
            "Investigation Agent",
            "model",
            "investigate",
            "Reads the evidence the retrieval agents assembled and reports what it shows: reported facts, evidence gaps, "
            "contradictions, risk indicators and limitations, each citing the source IDs it was given.",
            model_purpose="investigation",
            prompt=(
                "You are the Investigation Agent on an insurance claims-handling team. You are given the evidence the retrieval "
                "agents gathered and you report what it shows. You hold no tools and cannot fetch anything new, so you say what is "
                "missing instead of guessing. You do not recommend actions and you never decide a claim."
            ),
            cannot="Hold any tool. It reasons only over the evidence it is given.",
        ),
        _agent(
            "risk_analyst",
            "Risk and Priority Analyst",
            "rules",
            "risk",
            "Runs the trained models (settlement amount, days to resolve, fraud review signal) and scores handling priority from "
            "stated factors. Fixed rules and trained models; no language model and no knowledge base.",
            tools=("models.predict", "priority.score"),
            cannot="Call any knowledge-base tool or write a finding.",
        ),
        _agent(
            "recommender",
            "Recommendation Agent",
            "model",
            "recommend",
            "Turns the findings into a short list of next steps for the human handler. Each step says why it matters and cites "
            "its sources. It suggests; a person decides.",
            model_purpose="recommendation",
            prompt=(
                "You are the Recommendation Agent on an insurance claims-handling team. You are given the investigation's findings "
                "and propose next steps for the human claims handler. You hold no tools and cannot act on anything: each "
                "recommendation is a suggestion that a person reviews. You add no new facts and never decide coverage, payment or "
                "fraud."
            ),
            cannot="Hold any tool, or act: it can only suggest.",
        ),
        _agent(
            "validator",
            "Brief Validator",
            "rules",
            "validate",
            "Checks the finished brief against fixed rules: the right shape, every citation a real supplied source, and no action "
            "that decides a claim. Deterministic.",
            tools=("brief.validate",),
            cannot="Call any knowledge-base tool or change the brief.",
        ),
        _agent(
            "supervisor",
            "Supervisor Agent",
            "model",
            "supervise",
            "Reviews the finished brief before the handler sees it and writes a short plain-language summary. When the brief failed its "
            "checks in a way that rewording can fix, it sends the findings back to the Investigation Agent once with specific "
            "instructions, and the brief is checked again. It decides nothing about the claim.",
            model_purpose="supervision",
            prompt=(
                "You are the Supervisor Agent on an insurance claims-handling team. You review a finished brief before the human "
                "claims handler sees it. You hold no tools and cannot change the brief yourself: you can write a summary of it and "
                "ask the Investigation Agent to fix specific problems once. You never decide coverage, payment or fraud."
            ),
            cannot="Hold any tool, change the brief itself, or decide a claim.",
        ),
        _agent(
            "judge",
            "Independent Judge",
            "model",
            "judge",
            "A second model, kept different from the writers, reviews the brief against the evidence it cites. Advisory, runs in "
            "the background, and never changes the brief.",
            model_purpose="judge",
            cannot="Hold any tool or change the brief.",
        ),
        _agent(
            "operator",
            "Operator",
            "none",
            "",
            "Connection checks and the verification scripts: read-only reads of what the knowledge base holds. Not part of an "
            "investigation.",
            tools=(
                "trident_get_stats",
                "trident_episodes",
                "trident_get_schema",
                "trident_get_node",
                "trident_find_exact",
                "trident_cypher",
                "trident_get_chunks",
                "trident_search",
            ),
            cannot="Write anything to the knowledge base.",
            kind="system",
        ),
        _agent(
            "ingestion",
            "Ingestion job",
            "none",
            "",
            "The setup scripts and an administrator's promotion of a reviewed lesson: they load documents into the knowledge base, "
            "with the reads that verify a load. The only actor that may write documents.",
            tools=("trident_ingest", "trident_get_stats", "trident_get_chunks"),
            cannot="Send feedback or ask the query agent.",
            kind="system",
        ),
        _agent(
            "reviewer",
            "Human reviewer",
            "none",
            "",
            "The person who rates a knowledge-base answer as helpful, partly helpful or not. The only actor that may send feedback "
            "on an answer; no agent can.",
            tools=("trident_feedback",),
            cannot="Read the knowledge base.",
            kind="human",
        ),
    )
}


def agent(agent_id: str) -> AgentSpec:
    try:
        return AGENTS[agent_id]
    except KeyError:
        raise KeyError(f"Unknown agent: {agent_id}") from None


def investigation_agents() -> list[AgentSpec]:
    return [spec for spec in AGENTS.values() if spec.kind == "agent"]


def prompt_for(agent_id: str) -> str:
    """The role text an agent is given. The judge keeps its own, longer instructions in the judge module."""
    spec = agent(agent_id)
    if agent_id == "judge":
        from claims.evaluation import judge

        return judge.SYSTEM.rstrip()
    return spec.prompt


def describe(admin: bool = False, client_id_for=lambda agent_id: "") -> dict:
    """The roster as plain data, for the Agents page. Everyone gets names, purposes and what each agent can use, in vendor-free
    words; tool IDs, the identity an agent presents, the model setting and the prompt are for administrators."""
    agents = []
    for spec in AGENTS.values():
        row = {
            "id": spec.id,
            "name": spec.name,
            "kind": spec.kind,
            "method": spec.method,
            "stage": spec.stage,
            "purpose": spec.purpose,
            "cannot": spec.cannot,
            "can_use": [TOOLS[t].plain for t in sorted(spec.tools)],
        }
        if admin:
            row |= {
                "tools": sorted(spec.tools),
                "identity": spec.identity,
                "client_id_set": bool(client_id_for(spec.id)),
                "model_purpose": spec.model_purpose,
                "prompt": prompt_for(spec.id) if spec.method == "model" else "",
            }
        agents.append(row)
    result = {"agents": agents}
    if admin:
        result["tools"] = [
            {"id": t.id, "system": t.system, "plain": t.plain, "summary": t.summary, "writes": t.writes,
             "held_by": [s.id for s in AGENTS.values() if t.id in s.tools]}
            for t in TOOLS.values()
        ]
    return result
