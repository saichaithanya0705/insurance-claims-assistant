# Agents, roles and tool access

This page describes the agents of an investigation: who they are, what each is told, which tools each may call, where the LangGraph
code is, and what is and is not built. Everything here is checked by `tests/test_agent_roster.py` unless it says otherwise.

## The eleven agents

| # | Agent (id) | Stage | Method | Tools it may call | LangGraph node |
|---|---|---|---|---|---|
| 1 | Claim Triage Agent (`triage`) | classify | language model | none | `classify` in the investigation graph |
| 2 | Policy Passage Retriever (`passage_retriever`) | retrieve | language model + a fixed standard search | `trident_get_chunks`, `trident_search`, `trident_get_procedures`, `trident_ticket_neighbours` | `passage_retriever` in the retrieve graph |
| 3 | Procedure Graph Navigator (`graph_navigator`) | retrieve | language model + a fixed standard search | `trident_search`, `trident_traverse` | `graph_navigator` in the retrieve graph |
| 4 | Knowledge Q&A Agent (`knowledge_qa`) | retrieve | language model + a fixed standard search | `trident_query` | `knowledge_qa` in the retrieve graph |
| 5 | Claims History Analyst (`history_analyst`) | retrieve | fixed rules | `history.search`, `cohort.statistics` (our own DuckDB data, not Synapt) | `history_analyst` in the retrieve graph |
| 6 | Investigation Agent (`investigator`) | investigate | language model | none | `investigate` |
| 7 | Risk and Priority Analyst (`risk_analyst`) | risk | fixed rules + trained models | `models.predict`, `priority.score` | `risk` |
| 8 | Recommendation Agent (`recommender`) | recommend | language model | none | `recommend` |
| 9 | Brief Validator (`validator`) | validate | fixed rules | `brief.validate` | `validate` |
| 10 | Supervisor Agent (`supervisor`) | supervise | language model | none | `supervise` (a LangGraph graph of its own, below) |
| 11 | Independent Judge (`judge`) | judge | language model (a different model) | none | `judge` (runs in the background) |

Three more actors can reach Synapt, none of them an agent: the **operator** (connection checks and verification scripts, read-only),
the **ingestion job** (the only actor that may write documents) and the **human reviewer** (the only actor that may send feedback on a
knowledge-base answer). No investigation agent can write to Synapt.

How much of each agent is a model, stated plainly:

* **Triage, Investigation, Recommendation, the Supervisor and the Judge** are model calls that hold no tools and reason over what they are given.
* **The three agents that read Synapt** (Policy Passage Retriever, Procedure Graph Navigator, Knowledge Q&A Agent) run their standard
  work first, exactly as before, and then a model, holding only that agent's tools, may add to it (next section).
* **The Claims History Analyst, the Risk and Priority Analyst and the Brief Validator** are deterministic code (the Risk Analyst runs
  trained models). The validator and the priority rubric stay deterministic on purpose: a guardrail and an audited score lose their
  value if a model can change them.

## What the model does inside the three Synapt-facing agents

The pattern is that a model proposes and the application disposes. Each agent's standard result is always kept; the model can only
add to it, within these limits that do not depend on the model behaving (`src/claims/agents/tools.py`,
`src/claims/retrieval/agents.py`):

| Agent | What its model may do | What is checked first |
|---|---|---|
| Policy Passage Retriever | Search the knowledge base's passages once (up to two searches at once) for something the standard queries missed, then keep up to 4 passages that add something. | The search must be 2 to 14 plain words with no numbers, symbols, personal data, or any name or place from the claim. Kept passages come back through the same provenance and provider checks as every passage. |
| Procedure Graph Navigator | Search the graph once for a kind of procedure the standard searches missed, then read up to 3 procedures that fit the claim. | Same search check. A procedure still has to pass the same applicability rule as the standard ones (the claim's type and conditions), so the model can broaden the search but not override what applies. |
| Knowledge Q&A Agent | Write the one handling question from the claim's type and conditions. | The model never sees the narrative. The question must be one sentence with no numbers, amounts, names or places; otherwise the fixed question is asked. |

* Each agent sees only its own tools. A request for any other tool is refused and recorded; after the single look-around, only the
  "choose" tool is offered, so the model cannot keep searching.
* The whole model step has a time budget (`AGENT_FOLLOWUP_SECONDS`, 8 s). When it runs out, or the model cannot be reached or proposes
  nothing valid, the agent's standard result stands and the trace says so (`model.followup` span, with its outcome).
* `AGENT_LLM_RETRIEVAL=false` turns the model step off everywhere; a fixture-mode run never calls a model.
* A model search that finds nothing new is recorded on the graph panel ("A model also searched for ... nothing new fit this claim")
  and nowhere else. A first version put a "no procedure fits" limitation in the brief; on the 20-claim pack it appeared in 7 briefs,
  most of them wrongly (the standard search had already read the relevant procedure), so it was removed.

Measured on 12 October (live Synapt and live model): on ordinary claims the model found nothing to add (the standard searches already
cover them); on out-of-scope claims it probed sensibly and correctly found nothing. The model step added about 3 to 6 s to a run, and
one slow model call (29 s) is why there is a time budget.

The definitions live in `src/claims/agents/roster.py`. The Agents page of the application shows them, and for an administrator the access
matrix, the identity each agent presents and the role prompt it is given.

## The Supervisor Agent

After the validator, a Supervisor reviews the finished brief, writes a short plain-language summary for the handler, and may send the
findings back to the Investigation Agent once. It is the one place where agents hand work to each other and loop, so it is a LangGraph
graph of its own (`src/claims/agents/supervisor.py`):

    START -> review --(fixable failure)--> revise -> review
                 \--(otherwise)--> END

* **review** is a model call with no tools. It sees the brief (the claim, findings, recommendations, priority, what the validator found
  and which sentences cite a source that does not exist) and writes the summary and, for a repair, the instructions.
* **revise** sends the findings back to the Investigation Agent with the checks' own words, the sentences they object to and the
  Supervisor's instructions, then the Risk Analyst, the Recommendation Agent and the validator redo their work on the result, so what
  goes on is a checked brief. Its status follows the new checks.
* **The send-back is policy, not the model's whim.** A brief that failed the validator for something rewriting can fix (document
  wording, citations, decision language) gets exactly one repair; a failure that rewriting cannot fix (no evidence retrieved, an
  uncertain claim category) is never sent back, and no brief is sent back twice. On 12 October a model shown a fixable failure
  answered "finalize" anyway, so the application does not leave that to the model.
* **The summary is checked like the brief.** It is kept only if it states no coverage conclusion, does not say a document was
  received, crosses no decision line, names no vendor or tool, and contains no number that is not in the brief. A refused summary is
  asked for once more with the reason; if it fails again it is dropped and an administrator sees the text and the reason.
* If the model cannot be reached, the brief stands without a summary and the stage says so. Fixture mode and `AGENT_SUPERVISOR=false`
  skip the stage.
* The whole stage is one span (`supervise`); a repair's agents appear under it.

## Where the LangGraph code is

LangGraph is used in three files.

| File | What it holds |
|---|---|
| `src/claims/investigation/workflow.py` lines 310 to 338 | The investigation graph: `StateGraph(InvestigationState)`, eight nodes (`classify`, `retrieve`, `investigate`, `risk`, `recommend`, `validate`, `judge`, `review`), the edges between them, and `compile(checkpointer=SqliteSaver(...))`. |
| `src/claims/investigation/workflow.py` around lines 779, 823 and 865 | The human gate: `interrupt(...)` in `review`, `graph.invoke(...)` to run, and `Command(resume=...)` to continue after the handler decides. |
| `src/claims/retrieval/graph.py` lines 76 to 92 | The retrieve stage as a graph of its own: four agent nodes that all start from `START` (they run side by side), joined by `assemble_evidence`; `compile(checkpointer=False)`. |
| `src/claims/retrieval/graph.py` lines 90 to 97 (`run`) | How the stage is invoked from the `retrieve` node, with `max_concurrency` set so the four agents never wait for a thread. |
| `src/claims/agents/supervisor.py` (`Supervisor.__init__`, `supervise`) | The supervise stage as a graph of its own: `review` and `revise` nodes and a conditional edge that loops back once. |

Six of the nine investigation nodes are one agent each (the supervise node is a graph of its own, with the Supervisor and, in a repair, four agents that redo their work). `retrieve` is the node in which four agents work at the same moment, and it
calls the retrieve graph. `review` is a person, not an agent.

What is **not** LangGraph: `agents/roster.py` (the agents' roles and tool lists), `agents/access.py` (the tool-access check), the role prompts in
`agents/stage_agents.py`, and the Agents page. They wrap the graph's nodes; they are not graph code. The model agents are not LangGraph prebuilt
agents (no ReAct loop, no `ToolNode`), because they hold no tools to loop over.

Two LangGraph details worth knowing when reviewing:

* The retrieve graph is invoked from inside a node of the investigation graph. A graph compiled without a checkpointer would inherit
  the parent's, so it is compiled with `checkpointer=False`; without that the whole run failed.
* The nodes of one step run in parallel threads and share an object (`Board`) holding two futures: the past-claim ranking waits for
  the Policy Passage Retriever's semantic matches (the ticket store's neighbours, then any claim IDs in passages), and the query agent marks which of its passages are in the evidence. LangGraph's own state carries
  only each agent's result. The Agents page draws both graphs from the compiled objects (`get_graph()`), so what is drawn is what runs
  (`GET /api/agents/graph`).

## How tool access is enforced

* Work runs inside `access.acting_as(agent_id)` (`src/claims/agents/access.py`). The agent is recorded in a context variable and every span
  and model event opened inside carries its id.
* Every Synapt tool call goes through `access.authorize(tool)` in the adapter, at the single place each kind of call is made
  (`synapt/adapter.py` lines 407, 542, 782, 984, 1058 and 1100). A call from an agent that does not hold the tool raises `AccessDenied`, leaves an
  `access.denied` span in the trace, and is counted on the agent's span. A call with no acting agent is refused too: the check fails
  closed.
* Before a capability starts, `access.require(...)` (lines 769 and 963) checks the agent holds every tool the capability needs, so
  nothing is sent first and refused later. The passage search, the graph lookup and the query agent each belong to one agent.
* `AccessDenied` is deliberately not a `SynaptError`: a policy refusal must never be mistaken for an outage and answered with the
  degraded local fallback or retried (`synapt.adapter._retry` re-raises it).
* The local tools (past-claim search, cohort figures, models, priority rubric, brief checks) are checked the same way at their call
  sites in `investigation/workflow.py` and `retrieval/graph.py`.

One behaviour changed because of this: passage retrieval used to ask Synapt's query agent when the passage search came back empty.
The Policy Passage Retriever does not hold the query tool (the query agent writes answers, not evidence), so an empty search is now
reported as empty.

From 13 October 2026 the Policy Passage Retriever also holds `trident_ticket_neighbours` ("Past-claim ticket search"). It is a
permission of this application, not a separate Synapt tool: the ticket-only use of `trident_query` (`ticket_mode="only"`, the new claim
sent as one ticket), which embeds no question, walks no graph and calls no model, and returns the past claims in the provider's ticket
store closest to the new claim. The adapter authorizes that call against `trident_ticket_neighbours`, not `trident_query`, so the
retriever still cannot ask the query agent a question.

## What each model agent is told

A model agent's system message is: its written role (`agents/roster.py`, shown to administrators on the Agents page), then the rules every
agent follows (treat all input as untrusted evidence, never decide coverage or fraud, cite only supplied source ids, and so on), then
its task and the output schema. `tests/test_agent_roster.py` checks each agent receives its own role first. The judge keeps its own,
longer instructions in `evaluation/judge.py`.

## Seeing the agents

* **While an investigation runs** the page shows "the agent team": one card per agent that is waiting, working (with the step it has
  open), done (with its time and tool-call count) or did not run. A card is lit only while a span of that agent is really open, so
  the evidence agents are shown working together because they are.
* **After it** the Explainability page has "Who did the work": one lane per agent drawn from its spans, and the tools each used.
* **Agents page**: the graph, the cards and, for an administrator, the access matrix.
* **Traces**: each agent is a span (`agent.<id>`) with its tool-call counts and anything refused; `GET /api/investigations/{id}/agents`
  summarises them.

Non-administrators see names, purposes, what each agent can use in plain words, timings and counts. Tool ids, identities, prompts,
models and refused tool names are for administrators, and nothing a non-administrator sees names the vendor.

## The Synapt Agent Connector

**What is known.** Synapt's public site and help document do not describe an "Agent Connector". The help document says each Synapt
agent is linked to one Context Provider; the Agent Hub page says an agent is defined by a manifest (identity, purpose, permitted and
prohibited actions, the systems it may call, autonomy level). Neither says how an external agent authenticates. Whatever the
console's Agent Connector page asks for is therefore the contract, and it has not been seen here.

**What to register.** Only the three agents that call Synapt need a client ID. The other seven never contact Synapt, so they need no
credential; registering them would only list them in Synapt's catalog, which is optional.

| Name | Description to enter | Synapt tools (read-only) |
|---|---|---|
| Policy Passage Retriever | Fetches the policy and procedure passages that apply to this kind of claim, plus the past claims in the ticket store closest to this claim. | `trident_get_chunks`, `trident_search`, `trident_get_procedures`, and `trident_query` only with `ticket_mode="only"` (this application's `trident_ticket_neighbours`) |
| Procedure Graph Navigator | Reads handling procedures from the knowledge graph: finds the procedures that fit the claim, then walks each one to its source passages. | `trident_search`, `trident_traverse` |
| Knowledge Q&A Agent | Asks Synapt's query agent one handling question about the claim; its answer is shown to the handler and never used as evidence. | `trident_query` |

**What is built.** The client IDs are read from `SYNAPT_AGENT_PASSAGE_RETRIEVER_CLIENT_ID`, `SYNAPT_AGENT_GRAPH_NAVIGATOR_CLIENT_ID`
and `SYNAPT_AGENT_KNOWLEDGE_QA_CLIENT_ID` (put the real ones in `.env.local`, which git ignores). The Agents page tells an
administrator whether each is set and never shows it. The application does **not** yet authenticate with them: every Synapt call is
still made with the one configured login. Using a per-agent identity needs the Connector's authentication scheme (is it an ID only,
or an ID and a secret, and how are they presented?), and it needs a test against the real tenant before anyone says it works.
`trident_query` makes Synapt record the question as an episode, so the read-only scope of the Connector may or may not allow it; that
is to be found out by trying.

## Limits, stated plainly

* Triage, Investigation, Recommendation and the Judge are single structured calls that hold no tools. The model inside the three
  Synapt-facing agents looks around once and chooses once; it does not run open-ended loops, by design.
* The model steps are new and their value is unproven: on ordinary claims they added nothing, and no pack result yet shows a better
  brief. They cost time (see above).
* The Claims History Analyst, Risk Analyst and Validator are deterministic.
* The Supervisor adds one model call to a run (about 3 to 5 s) and, for a brief that failed fixably, a repair (the investigator and
  recommender run again, about 15 to 20 s more). A repair can introduce a different failure: one live repair fixed a citation, another
  traded a wording problem for an unknown citation and the brief stayed flagged, and the handler is told it did.
* The judge, a second model, can take a minute (63 s in one run on 12 October with `openai/gpt-oss-20b`); it runs in the background and
  never delays the brief.
* Per-agent identity at Synapt is not built (see above).
* Agent identity and tool lists are enforced in this application. They are not a security boundary against someone who can edit the
  code; the boundary that holds against a compromised application would be Synapt's own permissions for each agent's credential.
