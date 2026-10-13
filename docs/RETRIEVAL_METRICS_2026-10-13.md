# Retrieval metrics (13 October 2026)

The golden suite, the inline judge and DeepEval all score the finished brief. None of them says whether retrieval found the
right material, so a weak retrieval leg could hide behind a model that writes well. This measures retrieval on its own, with
standard information-retrieval metrics, against the live provider `synapt_capstone1`.

```powershell
uv run python scripts/evaluate_retrieval.py --output artifacts/evaluation/retrieval-2026-10-13.json
```

Read-only: passage search (`trident_get_chunks`), graph search and walk (`trident_search`, `trident_traverse`), and the ticket
leg of `trident_query` with `ticket_mode="only"` (no model call, no episode recorded). About two minutes. Two runs on
13 October gave identical numbers. Code: `claims.evaluation.retrieval` (metrics, labels) and `scripts/evaluate_retrieval.py`
(the live run); tests: `tests/test_retrieval_metrics.py`.

## Metrics

| Metric | Meaning here |
|---|---|
| precision@5 | Relevant documents in the top 5, divided by 5. Empty slots count as misses, so a short list is penalised |
| precision | Relevant share of what was returned |
| recall@5, recall | Share of the documents the claim needs that appear in the top 5, or anywhere (RAGAS: context recall) |
| hit@5 | Whether any needed document is in the top 5 |
| MRR | 1 / rank of the first needed document |
| nDCG@5 | Ranking quality with graded relevance, gain 2^grade − 1, against the ideal order |

## Ground truth

**Procedures.** 15 hand-labelled claims (`RETRIEVAL_QUERIES`) covering all five claim types and every condition procedure at
least twice. The first three are the golden cases. Each claim lists the SOPs a handler needs, read from each SOP's "applies
when" sentence. Grades: 2 = needed, 1 = general handling that fits any claim (REVIEW, CONFLICT, OUTSTANDING, PRIVACY,
FRAUD-SIGNAL), 0 = another claim's procedure. The labels are deliberately not derived from `knowledge_graph.applies`, the rule
the application uses to choose procedures; grading the system with its own rule would score it against itself. A unit test
checks that the threshold-based labels (late filing, large loss, repeat claimant, new policy) agree with the claim's fields.

Scoring is per document. Several passages or graph procedures from one SOP count once, at their best rank. A graph procedure
counts as the SOP whose passage Synapt extracted it from (`source_chunk_ids`). All 17 SOP passages were mapped.

**Similar past claims.** A returned past claim is relevant when it is the same claim type. nDCG is graded by how many of
five banded attributes it shares with the query (type, amount band, filing delay, tenure, claim history: the attributes the
ticket description is written from), against an ideal of every returned claim matching on all five.

**Known item.** 50 tickets from the uploaded workbook (10 per type, seed 7) sent back as queries: is each its own nearest
neighbour?

## Results

### Procedures (15 claims)

| Leg | precision@5 | precision | recall@5 | recall | hit@5 | MRR | nDCG@5 |
|---|---|---|---|---|---|---|---|
| Passage search | 0.35 | 0.37 | 0.69 | 0.69 | 1.00 | 0.93 | 0.61 |
| Knowledge graph | 0.83 | 0.86 | 1.00 | 1.00 | 1.00 | 0.97 | 0.92 |
| Both (what the brief writer sees) | | 0.61 | | 1.00 | | | |

* **The graph finds every procedure a claim needs** (recall 1.00 on all 15). The application builds one graph search per
  condition the claim meets, so condition procedures are found.
* **The passage search is a type search, and a weak one.** Its one query, "Synthetic {type} claim documentation procedure",
  is close to every "Synthetic … documentation procedure", so it returns the type procedures of other claim types:
  for an auto theft claim, the collision, property and business procedures. It never finds a condition procedure (theft, late
  filing, large loss, repeat claimant, new policy) unless the condition is in the type's own procedure. Its recall of 0.69 is
  almost all the type procedure itself.
* **Graph off-target results come from two procedures Synapt extracted from the auto SOP's passage.** "Human claims handler
  review" is general handling but its source passage is SOP-AUTO-001, so per-document scoring counts it as an auto procedure
  on 10 non-auto claims (a scoring artefact more than a retrieval error). "Police report request", also from SOP-AUTO-001,
  was chosen for the renters burglary: a real cross-type result, because its name names no claim type and the narrative
  mentions theft. One other: the business downtime procedure for a business claim that reports no lost income.

### Similar past claims for new claims (the same 15)

| Returned per claim | Same claim type | Attributes shared (of 5) | nDCG |
|---|---|---|---|
| 2.3 | 1.00 | 2.41 | 0.35 |

Every returned past claim is the right type. Beyond type they share about 1.4 of the other 4 attributes. That is expected
from how the ticket leg works: per label field it returns the closest ticket for each label value (approved, denied, flagged,
not flagged), not the k closest tickets, so it deliberately includes the closest *denied* claim even when the closest claims
are all approved.

### Known item (50 stored tickets)

| Found itself | hit@1 | MRR | hit@1 when found | Store held out by Synapt |
|---|---|---|---|---|
| 0.80 | 0.80 | 0.80 | 1.00 | 0.20 (400 of 2,000) |

Every ticket that came back came back first. The 10 that did not come back at all are 20 % of the sample, the share
Synapt holds out of the neighbour pool for its own accuracy scoring (`trident_get_stats` → `ticket_mining.held_out`). Which
tickets are held out is not exposed, so this is an inference, not a check.

## What changed (13 October 2026)

**Passages are now matched to the graph before they reach the brief.** A standard passage stays in the evidence only when
it is the source of a procedure the graph chose for this claim's type or conditions (`knowledge_graph.backed_passages`,
applied in `claims.retrieval.graph.assemble_evidence`; the trace records what was dropped in an `evidence.passages` span).
Passages the model's follow-up kept always stay. If the graph lookup fails or chooses nothing, every passage stays, as
before. The search itself is unchanged: it still runs, and it still carries the ticket-store lookup.

| What the brief receives | precision | recall | MRR | nDCG@5 |
|---|---|---|---|---|
| Passages, before | 0.37 | 0.69 | 0.93 | 0.61 |
| Passages, after | **0.94** | 0.69 | 1.00 | 0.64 |
| Passages and graph procedures, before | 0.61 | 1.00 | | |
| Passages and graph procedures, after | **0.86** | 1.00 | | |

Recall is unchanged: every passage dropped was another claim's procedure. The remaining off-target passage is the auto
SOP's on the renters burglary, kept because "Police report request" was extracted from it (below).

**The DeepEval judge is now a different model from the writer.** `DEEPEVAL_MODEL` was `nemotron-3-super-120b`, the model
that writes the brief, so the suite was grading its own author. It is now `openai/gpt-oss-20b`, the inline judge's model,
and the suite's `judge_independent` now checks every stage model (`Settings.writer_models`), as the inline judge does.

**Not changed:** a graph procedure is still matched to a claim by its own name and intent, not by the SOP it was extracted
from, so "Police report request" (from the auto SOP) can still be chosen for a renters theft.

Limits: 15 claims is a small, hand-written set; the labels are one reader's judgement of the SOPs' "applies when" sentences.
The model follow-ups of a live investigation (the passage retriever's and graph navigator's extra searches) are not
included; they only add to the standard results measured here.
