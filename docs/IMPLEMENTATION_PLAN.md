# Implementation plan

Decision: Python LangGraph orchestration, Synapt MCP knowledge boundary, FastAPI microservice,
SQLite local persistence, scikit-learn numerical models and an accessible dependency-free frontend.
Keep model provider configurable. LangGraph execution state and Synapt domain memory are separate.

## Sequence and acceptance

1. Contracts, fixture spine and saved review: reproducible app without credentials.
2. Historical retrieval/filtering and comparable-case differences: temporal source availability.
3. Amount/duration/fraud models on the specified dataset: honest holdout/baselines and provenance.
4. Four bounded agents plus deterministic gates: real provider path and explicit fixture path.
5. Evidence-linked UI, prioritization, feedback candidates and evaluation: complete local workflow.
6. Dedicated Synapt provider, schema discovery and pilot ingestion: pending team access.
7. Live regression, quality review, measured expansion and ten-minute presentation.

Features 1–5 have code paths in this repository; they require actual validation results in
VALIDATION.md, not a declaration of live readiness. Features 6–7 remain release gates.

## Boundaries

Only known read tools can supply retrieval context. MCP schemas are discovered and validated.
Unknown or provenance-free responses fail. External writes are explicit single-attempt CLI
operations. No claim approval/denial/payment endpoints exist. Handler review accepts the brief,
not insurance coverage. Reviewed feedback becomes a candidate lesson, never automatic truth.

Keyword BM25 and feature comparison use the local historical table. Synapt supplies semantic
matches and graph/procedure context; identified historical claim IDs can join the candidate list
for reciprocal-rank fusion. Eligible outcomes must predate the current claim. A real hybrid-search
quality claim requires live Synapt results, ingestion of stable IDs and independent relevance labels.

## Agent objectives

Intake: classify supported lines or abstain. Investigator: explain meaningful comparisons,
evidence gaps and contradictions. Risk analyst: distinguish statistical risk, urgency and limitations.
Writer: recommend useful next actions with sources. LLM outputs are schema-validated; member-ID
checks are insufficient proof of grounding, so human review and measured semantic evaluation remain.

## Ten-minute presentation

1 minute problem; 2 minutes Synapt architecture and provenance; 4 minutes ordinary/missing/conflicting
cases; 2 minutes test and statistical results; 1 minute limits and expansion. Include a proper abstention.
