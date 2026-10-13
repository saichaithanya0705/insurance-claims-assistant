# Observability, traces and explainability

Added 7 October 2026. Every investigation now leaves a **trace**; two new pages show what the system is
doing (**Observability**) and why a brief says what it says (**Explainability**); and each brief carries an
account of **how it was generated** and **how it was evaluated**.

| You want to know | Where | Who |
|---|---|---|
| How is the system behaving: volume, latency, failures, model use? | Observability, Overview | Administrator |
| What exactly happened for one query, step by step, with timings? | Observability, Query traces | Administrator |
| Why does this brief say this, and what stands behind each statement? | Explainability, or the **Explain** tab of any brief | Handler and administrator |
| How was this brief checked before anyone relied on it? | The Evaluation section of the same page | Handler and administrator |

Everything is derived from what the run stored plus the trace recorded while it ran. No model is called
and no search is repeated to explain a brief. The one thing recomputed is the deterministic validation, as a
cross-check against the verdict that was saved. Anything that was not recorded is labelled as such rather
than guessed.

## The trace

A trace is a tree of **spans**: one root per run, one span per workflow stage, and spans for the work inside
each stage. Spans are written to SQLite as they close, so a run that fails part-way still leaves the trace of
everything it did before failing.

```
investigation                      (run)        total time until the brief was ready
├─ classify                        (stage)
│  └─ llm.classification           (model)      model, attempts, tokens, finish reason
├─ retrieve                        (the next four overlap in time: cohort.statistics starts first)
│  ├─ cohort.statistics            (compute)    DuckDB figures; its cross-check waits for the passage search
│  ├─ knowledge.retrieve           (service)
│  │  └─ synapt.retrieve           (service)    attempts; list_tools, search calls with their queries, and the
│  │                                            ticket-store call for similar past claims (trident_query, ticket_mode=only)
│  ├─ knowledge.graph              (service)    the graph lookup, started once the passages are in
│  ├─ history.search               (retrieval)  candidates, per-method ranks and points per result
│  └─ feedback.lessons             (retrieval)
├─ investigate  └─ llm.investigation
├─ risk         ├─ models.predict  └─ priority.score          (computation)
├─ recommend    └─ llm.recommendation
├─ validate                                    every rule, with how many items it inspected
├─ judge        └─ judge.review    (background) └─ llm.judge
└─ review                          (stage)      "waiting" until a handler decides
handler_review                     (run)        a second root, recorded when the handler decides
```

* **Time.** Durations are measured (`perf_counter`), start times are UTC. The handler's wait is not part of
  the investigation's run time; the independent review runs in the background and is shown but not counted
  as time spent waiting for the brief. Anything recorded inside background work inherits the flag.
* **Model calls.** One span per call with the purpose, model, attempts (each with its outcome, HTTP status
  and duration), prompt and answer size, the finish reason and the token usage *as the provider reported it*.
  If the provider reports none, none is recorded; nothing is estimated. The span points at the audit events
  that hold the full prompt and answer, which an administrator can open on demand.
* **Never recorded.** Credentials, authorisation headers, reasoning traces, and provider error messages. A
  failed span stores the exception *type* only. Attribute values are sanitised (no NaN, bounded in size,
  an oversized value is replaced by a marker rather than cut in half).
* **Observing never breaks the work.** If a span cannot be written the failure is logged and the
  investigation continues. Code that is not inside a trace (the stand-alone search endpoint, scripts, tests)
  records nothing and needs no changes.

### Runs saved before tracing existed

Existing runs have no spans, but they have audit events: stage completions, model prompts, outputs and
failures with timestamps and token usage. The trace for such a run is **reconstructed** from those. A stage's
duration is the gap since the previous stage finished; a model call runs from its prompt to its answer.
These are approximations, retrieval and scoring internals do not exist for them, and every reconstructed span
and page says so ("Reconstructed" badge, an explanatory notice, "Approximate" on each span). Token totals of
reconstructed runs match the audit log exactly (a test checks every run in the shipped template database).

## Observability page (administrators)

**Overview.** One filter row (time range, handler queries or evaluation-suite runs) scopes every figure below
it. While a new scope loads, the previous figures stay on screen, dimmed.

* Headline figures: queries (and how many failed), median and 95th-percentile run time, model calls
  (retried, failed), tokens per query, validation pass rate, independent-review pass rate.
* Queries over time; outcomes; time per stage (median with 95th-percentile tick); model usage by purpose;
  recent errors (type only) that open the failing trace; quality gates; every operation; API traffic by
  route template.
* Every chart has a **Table** view with the same values, and shows the same detail on hover and keyboard
  focus. The 3-series ranking chart uses colour slots that pass a colour-blindness check; the application's
  own muted tones do not (two of them differ by 0.5 perceptual units under red-green colour blindness).
* A footnote reports how many runs were recorded live and how many reconstructed.

**Query traces.** Every saved query, newest first, searchable and filterable by outcome, with run time, model
calls, tokens, validation and review. Opening one shows:

* Run time, model calls (time waited on models, separate from background time), tokens, steps.
* An **execution timeline** (waterfall) on one time axis. The axis ends when the brief was ready; the
  background review is drawn running off the edge, and a switch shows it to scale. Work recorded after the
  run (the handler's review) sits off the axis.
* A **detail panel** for the selected step: for a model call, the attempts, token split and buttons to load
  the full prompt and the validated answer; for everything else, what the step recorded.
* **Export JSON**, and **Explain this answer**, which opens the same query in Explainability.

## Explainability page (everyone)

Pick a query (search, or the recent chips) to see, in order:

1. **How the brief was generated.** The eight stages, each marked with what made the call: an AI model,
   fixed rules, search and ranking, statistical models, or a person; what it read and produced; how long it
   took.
2. **Where each statement came from.** Every finding and recommendation with the exact sources behind it
   (submitted claim, handling procedure, comparable claim, reviewed lesson). A statement with no source is
   flagged, not hidden.
3. **How comparable claims were found and ranked.** The pool, the three methods and their weights, the
   formula `1/(60+keyword rank) + 1/(60+numeric rank) + 0.5/(60+semantic rank)`, the candidate funnel, and a
   stacked bar per comparable claim showing each method's share of its score, with the ranks written out.
   The semantic rank is the order in which Synapt's ticket store returned similar past claims (2 to 4 per claim
   since 13 October 2026); a claim it adds is labelled "Related in meaning: Synapt's ticket store ranked this
   past claim #N". Administrators also see what the knowledge store was asked.
4. **Why this handling priority.** The meter with tier thresholds, the points to the next tier, and the full
   rubric: which factors applied, which did not, and what each earned.
5. **What the model estimates rest on.** For amount, resolution time and fraud flag: the value, the interval
   or threshold, the features that moved this claim's estimate (with typical values), and what the model
   learned overall. Features that did not move an estimate are not listed.
6. **How the brief was evaluated** (below).
7. **Boundaries and limitations.** What the system will not do, and what is not known for this brief.

### How a brief is evaluated

| Layer | What it is | Gate? |
|---|---|---|
| **Mechanical validation** | Eight deterministic rules, no AI: external evidence retrieved, findings cite a source, citations resolve, no unverified document-receipt claims, recommendations cited, actions and text stay inside the decision boundary, category confident. Each rule reports how many items it inspected and how many failed. Re-running them on the saved brief gives the same verdict as the one saved (shown). | Yes: a brief that fails cannot be accepted |
| **Evidence grounding** | Counts: substantive findings that cite a source, citations that resolve, recommendations that cite a source, retrieved sources the brief draws on. A citation proves a source was named, not that it supports the claim. | No |
| **Independent AI review** | A second, different model: grounded, inside the boundary, recommendations supported, a 0 to 1 score with the 0.70 passing line, issues. Advisory and probabilistic. Administrators also see which model reviewed it and whether it was independent. | No |
| **Handler review** | A person accepts the brief or requests a revision. Never approves, denies or pays the claim. | Yes |
| **System evaluation suite** (administrators) | The golden claims, and the model-graded metrics when they were run. A regression check on the system, not a score for this brief. | No |

The validation rules are `VALIDATION_CHECKS` in `investigation/workflow.py`. `validate_brief` still returns the same
`passed` and `issues` as before; `checks` is added alongside.

## Who sees what

Handlers never see model or provider names, prompts, token counts, retrieval queries or raw trace data; the
explanation they get is written without them (`observability/explain.py` applies the same wording rules as the brief
itself). Administrators see all of it. The rules are enforced by the API, not just hidden in the interface.

| Endpoint | Handler | Administrator |
|---|---|---|
| `GET /api/investigations/{id}/explanation` | Own queries only (404 otherwise) | All |
| `GET /api/investigations/{id}/trace` | 403 | Yes |
| `GET /api/investigations/{id}/audit/{event_id}` (one prompt or answer) | 403 | Yes |
| `GET /api/traces` (list with trace figures) | 403 | Yes |
| `GET /api/observability/summary?window=24h\|7d\|30d\|all&origin=all\|user\|evaluation` | 403 | Yes |

## Storage

Additive and automatic on first start; no manual migration.

* `spans` (one row per span) and `api_requests` (method, route template, status, latency, role; the newest
  20,000 rows are kept) are new tables in the claims database.
* An index on `audit(run_id)` is added (the audit table had none, so every per-run lookup scanned it).
* Route templates, not URLs, are logged, so run identifiers never enter the request log.
* A fresh clone gets the shipped sample runs with reconstructed traces immediately.

## Measured

On the real 22 MB database (76 runs, 70 of them reconstructed) the dashboard summary takes about 25 ms and a
trace under 1 ms. With the real workflow, live-style agents on a mocked model transport and a stubbed Synapt
session, a run records 23 spans including the retried model call, both Synapt calls and the background
review.

| Check | Result |
|---|---|
| Backend tests | `tests/test_observability.py` (19) and `tests/test_explain.py` (16) added; the whole suite passes (349 tests) |
| Frontend tests | `frontend/tests/observability.test.cjs` (19) added; 35 in total pass |
| Lint and types | `ruff check src tests scripts`, `tsc -b` and `oxlint` introduce no new findings |
| Real browser | Administrator and handler views, deep links between pages, the prompt viewer, a reconstructed run, and a 375 px viewport (no horizontal overflow) |

## Limits

* Tokens are those the provider reports; there is no price table, so no cost figures are shown.
* A reconstructed trace cannot show retrieval ranks, scoring internals or the Synapt calls of that run.
* Spans are kept for the life of the database; the request log is capped, spans are not. Pruning policy is
  left to the operator.
* The judge's verdict can arrive after the brief is shown, so the Overview can briefly count a run's review
  as pending.
* The service is a single process; traces are not shipped to an external collector.

## Evaluation runs (Observability, administrators)

The evaluation suite (Quality & models) runs the golden cases as ordinary traced investigations (origin "evaluation") and,
when selected, asks an LLM judge to score each case's brief on three metrics. The judge works after the investigation has
finished, so its calls are recorded afterwards under that run's root span: a `judge.metric` span per metric with an
`llm.judge_metric` span per model call, all flagged background (they never count as time a handler waited, and a run's duration
is unchanged). The **Evaluation runs** tab lists the recent runs from the audit log: golden cases passed, judge status and
model, metrics scored and met, mean score, judge model calls, duration, and a button for each case's trace. Runs saved before
this change show "Not traced" for the judge calls. The judge's scores themselves are unchanged and are also on the Quality page.
