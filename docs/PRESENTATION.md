# Panel presentation: ten minutes

The deck is [Claims_Assistant_Panel_Deck.pptx](Claims_Assistant_Panel_Deck.pptx): nine slides with
the spoken script in each slide's speaker notes. It is built by `scripts/build_deck.js` from the facts in
[VALIDATION.md](VALIDATION.md), [MODEL_CARD.md](MODEL_CARD.md) and
[SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md).

## Timing

| Slide | Time | Message |
|---|---:|---|
| 1. Title | 0:30 | 100 million claims queried in place, 1,000 claim cards in Synapt, 8 stages, one human gate |
| 2. Three questions | 1:00 | Each of the brief's three questions has a capability behind it |
| 3. Architecture | 1:15 | One service, three stores, one human gate; Synapt cannot hold 100 million claims, so each store does what it can |
| 4. Hybrid search | 1:30 | 3 to 5 seconds over 100M rows; how the ranks are fused; the IDF bug found by measuring |
| 5. Synapt | 1:15 | Masking broke the identifiers; the fix; the measured precision is real but mild |
| 6. Live demo | 1:45 | Auto-theft claim: cited gap, audited priority, independent review, lesson loop |
| 7. Predictions | 1:00 | Error against baseline, and "why this estimate" |
| 8. Evaluated, guarded, learning | 1:15 | Golden cases, DeepEval, guardrails, the closed feedback loop |
| 9. Limits and next | 0:30 | Honest limits; "Evidence informs. A person decides." |

## Before the panel

1. `uv run python scripts/bootstrap.py check` ends with **READY** and shows the Synapt provider's counts.
2. Start the service: `uv run uvicorn claims.api:app --host 127.0.0.1 --port 8000` and sign in.
3. Set `JUDGE_MODE=inline` in `.env` if you want the independent review on screen (it adds a verdict
   about 15 to 60 seconds after the brief; the brief itself appears in about 15 seconds).
4. Open **Quality & models** once so the model status is warm. Do not press **Train models** on stage
   (it takes about 80 seconds).
5. If a network or provider fails, set `SYNAPT_MODE=fixture` and `AGENT_MODE=fixture` and restart: the
   whole interface still works, and you should say so aloud ("this is fixture mode").

## Demo script (slide 6, 1:45)

1. **Investigation, then the Auto theft example.** Point out "Try an example", then build the brief.
2. While it runs (about 15 s): "Retrieval, three model calls and a validator are running."
3. **Brief tab.** The police-report **gap** is cited to a Synapt procedure; each citation opens the
   source. Documents are only ever "reported available".
4. **Handling priority**: High, 55 of 100, five attributed factors.
5. **Comparisons tab**: the five closest claims (same type and state, amount within $100, same prior
   claims) and the "Related by meaning" ones with their Synapt rank; one carries the dataset fraud flag.
6. **Model estimates**, open one **Why this estimate**: the direction of each effect and what moved this claim.
7. **Independent review** appears when the background judge finishes.
8. **Review**: accept the brief, rate it, then as administrator open **Quality & models** and **Promote**
   the lesson; rerun the claim and show the lesson cited in the evidence.

## Likely questions, answered honestly

**Why isn't the whole dataset in Synapt?** Its ingestion tool takes about 100 cards per call and each call
takes minutes; 100 million cards would take years. So the Parquet file is the authority for filters,
numbers and models, and Synapt holds procedures, a 1,000-card sample for semantic ranking, and lessons.
If instructors expect the full dataset in Synapt, a ticket-store provider uploaded through the console
is the route to try; it was not testable here.

**Does Synapt's semantic search actually help?** A little, and I measured it: its cards match the query
claim's type 1.7 times as often as chance and its amount band 1.5 times, and are no better than chance
on prior claims. That is why it carries half the weight and its extra picks are shown separately.

**How reliable is the fraud model?** At its threshold, about half the claims it flags carry the dataset
flag (precision 56%) and it finds under a third of them (recall 31%). It is a screening aid on synthetic
data, and the interface never calls anything fraud.

**What does the independent judge add?** A second, different model reviews each brief against its evidence.
It is advisory and probabilistic: it is not a gate. The deterministic citation and boundary checks are the
gate, and the handler decides.

**How does feedback improve it?** Not by retraining on its own. A person rates an accepted brief, an
administrator promotes the lesson, and it is cited as evidence in later investigations of the same
claim type and ingested into Synapt. Nothing is promoted automatically.

**DeepEval shows failures. Why?** Eight of twelve live metrics pass. Contextual Relevancy is the weak one
(1 of 4): the retrieval context deliberately includes comparison claims and procedures, which the metric
counts as off-topic. Faithfulness and the safety metric are strong.

**What did you find by testing live that tests did not?** Four things: Synapt rewrites identifiers and
place names; BM25's IDF let diverse outliers outrank exact matches; the token endpoint rate-limits
repeated logins; and an inline judge could stall a brief for over a minute. Each is fixed and has a test.

**Is this production-ready?** No. It is a local educational service on synthetic data: SQLite, one
process, no MFA or single sign-on, and no claim of real-world accuracy.
