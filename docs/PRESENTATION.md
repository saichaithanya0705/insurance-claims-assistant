# Panel presentation: ten minutes

The deck is [Claims_Assistant_Panel_Deck.pptx](Claims_Assistant_Panel_Deck.pptx): nine slides with
the spoken script in each slide's speaker notes. It is built by `scripts/build_deck.js` from the facts in
[VALIDATION.md](VALIDATION.md), [MODEL_CARD.md](MODEL_CARD.md) and
[SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md).

## Timing

| Slide | Time | Message |
|---|---:|---|
| 1. Title | 0:30 | 100 million claims queried in place; Synapt holds 17 procedures as documents and 2,000 settled claims in its ticket store; 8 stages, one human gate |
| 2. Three questions | 1:00 | Each of the brief's three questions has a capability behind it |
| 3. Architecture | 1:15 | One service, three stores, one human gate; Synapt cannot hold 100 million claims, so each store does what it can |
| 4. Hybrid search | 1:30 | 3 to 5 seconds over 100M rows; how the ranks are fused; the IDF bug found by measuring |
| 5. Synapt | 1:15 | Procedures as documents (and the graph Synapt extracts), past claims in the ticket store; the split corrected on 13 October after review; masking broke the identifiers, and the fix |
| 6. Live demo | 1:45 | Auto-theft claim: cited gap, audited priority, independent review, lesson loop |
| 7. Predictions | 1:00 | Error against baseline, and "why this estimate" |
| 8. Evaluated, guarded, learning | 1:15 | Golden cases, DeepEval, guardrails, the closed feedback loop |
| 9. Limits and next | 0:30 | Honest limits; "Evidence informs. A person decides." |

## Before the panel

1. `uv run python scripts/bootstrap.py check` ends with **READY** and shows the Synapt provider's counts.
2. Start the service: `uv run uvicorn claims.api.main:app --host 127.0.0.1 --port 8000` and sign in.
3. Set `JUDGE_MODE=inline` in `.env` if you want the independent review on screen (it adds a verdict
   about 15 to 60 seconds after the brief; the brief itself appears in about 15 seconds).
4. Open **Quality & models** once so the model status is warm. Do not press **Train models** on stage
   (it takes about 80 seconds).
5. If Synapt or the network fails during the demo, the application keeps working in a clearly labelled **degraded
   mode**: the five original procedures and the similar-claim ranking come from local copies (a local index of
   claim cards that exists only on this machine, not in Synapt), the brief
   carries a "Degraded mode" limitation, and `/api/health` shows `last_retrieval: local_fallback`. Say so aloud.
   Run `bootstrap.py check` and `prepare_fallback_index.py` before going on stage so the local index is cached.
   To show it deliberately, start a second copy with `SYNAPT_AUTH_BASE=https://127.0.0.1:9/auth/token`: it behaves
   as if Synapt were down. Live Synapt remains the normal path and the one being demonstrated.

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

**Why isn't the whole dataset in Synapt?** Document ingestion took about 100 claim records per call and each
call took minutes, and a ticket store is a sample, not 100 million rows. So the Parquet file is the authority
for filters, numbers and models. Synapt holds the 17 handling procedures as documents (it extracts the graph
from them: 21 procedures, 93 ordered steps), 2,000 settled past claims in its ticket store (400 per claim
type), promoted lessons, and its own episodic memory.

**Was the data split in Synapt right?** Not at first. Until 13 October the provider held the procedures and
10,000 claim records written as text "cards" in the document store. The review said that was wrong, and
measuring agreed: the cards were 99.6% of the chunks but had 55 graph links against 135 from the 17 procedure
chunks, and they crowded the procedures out of passage search. On 13 October 2,000 settled claims went into the
ticket store and the cards were deleted; the provider now holds 18 documents and 39 chunks. A live check of
three investigations (auto, home and one with no type) returned procedure passages, graph procedures and 2 to
3 ticket-store claims for each; the judge passed the auto and home briefs (0.95 and 0.92) and the typeless
claim went to manual review, as designed.

**Does Synapt's similar-claim lookup actually help?** Not measured yet, which is why its role is small. The
ticket-store lookup (`trident_query` with `ticket_mode="only"`: no question, no graph walk, no model) names 2 to
4 past claims; they are looked up in the Parquet file under the handler's filters, carry half the weight in the
fused rank and can add at most 3 claims. The former 10,000-card corpus matched the query claim's type 4.4 times
as often as chance and was barely better than chance on prior claims (1.1 times). The ticket store's own
outcome and fraud labels are ignored: in trials they never beat guessing the majority class.

**Is Synapt learning from use?** Not verified yet. Its episodic memory holds 22 lived episodes
from query-agent sessions; none has been mined yet, and mining cannot be started over MCP (it is a console
step), so I make no claim about mined episodes.

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
