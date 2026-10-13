# Synapt integration

What Synapt does in this system, what was measured against the real tenant on 2026-10-06, and
what to know before changing it. Commands are in [SETUP.md](SETUP.md). The wire-level contract
(authentication shape, tool names, argument schemas) is in [SYNAPT_CONTRACT.md](SYNAPT_CONTRACT.md).

## How the data is split across Synapt (corrected 13 October 2026)

Synapt has two stores for two kinds of content, and the provider now uses each for what it is for:

| Content | Synapt store | Why |
|---|---|---|
| 17 handling procedures (SOPs) | Documents, so the Knowledge Service extracts the graph: 21 procedures, 93 ordered steps, rules and roles | Procedures are knowledge: steps, responsibilities and rules |
| 2,000 settled past claims | The ticket store (console: Data Ingestion, Ticketing), labels `resolution` and `fraud_flag` | A settled claim is a case with an outcome, which is what a ticket store holds and what episode mining reads |
| Answers and handler ratings | Episodic memory (`es_synapt_capstone1`), written by Synapt | What the query agent has learned |
| All 100 million claims, every figure shown | DuckDB over the Parquet file, outside Synapt | Exact filters and numbers |

Until 13 October the provider also held 10,000 claim records written out as text "cards" (20 documents). Measured from the
graph before they were removed: the 20 card documents were 10,020 of 10,059 chunks (99.6 %) and had 55 links into the
graph, while the 17 procedures (17 chunks) had 135. The cards added almost no knowledge and crowded the procedures in
passage search. Review feedback called this split wrong; it was. The claims were uploaded as tickets to the same provider
(`claims_tickets_capstone1.xlsx`, the same 2,000 rows as the `ticket_mining` trial; ID `ticket_id`; embedded `title`,
`description`, `category`, `region`; predicted `resolution`, `fraud_flag`; everything else stored only), checked (38
documents, 21 procedures, 93 steps and 141 entities unchanged; provider kind became `ticket_mining`), and then the 20 card
documents were deleted in the console. The provider now holds 18 documents and 39 chunks; 93 entities remain (the 48
removed came from the cards' header chunks).

**How the application uses it now.** Passages and graph procedures come from the documents, as before. Similar past claims
come from the ticket store: the Policy Passage Retriever sends the new claim as one ticket (the same four embedded
columns, built by `claims.corpus.cards.claim_ticket`, which also writes the workbook) to `trident_query` with
`ticket_mode="only"`, which embeds no question, walks no graph and calls no model. The retriever holds a separate
permission for this (`trident_ticket_neighbours`); it still cannot ask the query agent a question. The ticket IDs of
the neighbours Synapt names are claim aliases, decoded and looked up in the Parquet file under the handler's filters,
exactly as card aliases were. Synapt names one neighbour per label value, so a lookup gives 2 to 4 claims (the card
search gave up to 20); they add a semantic rank to the DuckDB search and can add up to 3 claims to it. The labels and
confidences themselves are ignored: on this data they never beat the majority class (see the ticket-store trials below).
Chunks of Synapt's episodic document are no longer treated as evidence: they record what an agent once asked, not policy.

**Measured on 13 October** (three live investigations, auto, home and a claim with no type): passages, graph procedures
and 2 to 3 ticket-store claims for each; the judge passed the auto and home briefs (0.95, 0.92); the typeless claim went
to manual review as designed. `scripts/verify_synapt_store.py` checks the procedures, the ticket store (count, ID and
label fields) and that no large non-procedure document is left.

**Episode mining has not happened yet.** All 22 episodes in the store are lived ones from 12 October query sessions;
none is mined. No MCP tool starts mining (`trident_episodes` only reads), so it has to be started from the console
(Observability, Episodic Mining Dashboard) or happens on Synapt's own schedule. Not verified until mined episodes appear.

## Role

| Synapt holds | Used for |
|---|---|
| 17 hand-authored handling procedures (SOPs: 5 short ones, and 12 written as ordered steps on 12 October 2026), and the knowledge graph Synapt extracted from them (21 procedures, 93 ordered steps, linked rules) | Passages and graph procedures are both cited as evidence in findings and recommendations; see [Knowledge graph](#knowledge-graph-read-for-every-investigation-from-12-october-2026) |
| 2,000 settled past claims in the ticket store (400 per claim type, the dataset's own fraud and denial rates) | Semantic ranking of similar claims (until 13 October: 10,000 claim cards as documents; see above) |
| Reviewed handler lessons, ingested when an administrator promotes one | Shared knowledge; also reused locally as cited evidence |

It does **not** hold the 100 million claims. The Parquet file does, and it is the authority for every
filter, every number shown and every model. Synapt returns identifiers, which are looked up in the
Parquet file under the handler's filters.

### Knowledge graph, read for every investigation (from 12 October 2026)

Until 12 October the application read Synapt only as passages (`trident_get_chunks`, a vector search over chunk text);
the graph Synapt builds at ingestion was used only to verify the store. `claims.synapt.knowledge_graph` now reads the graph
itself for every investigation, in its own call after passage retrieval, so a failure there cannot break retrieval:

1. `trident_search(node_type="Procedure", top_k=15)` finds procedure nodes by meaning, with a score. One fixed search for
   the claim type, one for general handling, and one for each **fact cue** the claim meets (below). The text sent is fixed
   vocabulary plus the claim type, never the claimant's narrative. The width (15) is deliberate: the procedures are worded
   alike, so a procedure that fits can rank below several that do not (the collision procedure was missed at 6).
2. **An applicability check, which is ours.** Measured on the live graph, the search ranks by wording, not claim type: for
   an auto claim the business-loss procedure scored 0.88 against 0.87 for the auto one. A procedure whose name or intent
   names another claim type is set aside; one that names this type is kept; one that names none is general handling. A
   procedure that applies only under a condition is kept only when the claim meets that condition. **Fact cues**, worked
   out from the structured claim (and, for theft and water damage, a keyword check on the narrative that is never sent):
   theft; water damage; filed more than 30 days after the incident; claimed amount of $50,000 or more; three or more
   earlier claims; policy in force for less than a year. The thresholds are the ones this application already uses to point a
   claim out, not insurer rules, and the procedures say so. A "no theft" procedure is set aside for a theft claim. The page
   shows the cues as chips and lists every search hit with the reason each was set aside. At most 8 specific and 3 general
   procedures are kept.
3. `trident_traverse(edge_types="HAS_STEP,PRECEDES,REFERENCES", depth=2)` walks each kept procedure to its ordered steps
   (with prerequisite and responsible role) and to the rules, controls and tasks those steps reference.
4. **Citable.** Every Procedure and Entity node lists the passages it was extracted from (`source_chunk_ids`); these are
   the same `chunk_<uuid>` IDs passage evidence is cited by. Each graph procedure becomes an evidence item
   `graph:procedure:<id>` (provenance `synapt`) whose text is Synapt's extracted steps and links plus "Extracted from
   passage(s): chunk_…". An earlier comment that graph output was "uncitable" was wrong for these nodes.

Read-only: `trident_search` and `trident_traverse` write nothing.
About 5 to 7 calls and 3 to 5 seconds per investigation; the interactive case search skips it. On failure the run
continues with passages only and carries a limitation finding ("The Synapt knowledge-graph lookup failed..."); a
degraded (local fallback) run reads no graph. The Evidence tab shows the procedures as numbered steps with their linked
rules and source passage, above the evidence library, and the trace records `knowledge.graph` and each tool call
(`purpose` `graph_search` and `graph_walk`).

**What the live writer does with it** (12 October, three live-model runs, all validated): with one added prompt sentence
(prefer citing a `graph:procedure:` item when it states a documentation requirement) the gap findings cited the graph
procedure ("Incident statement and repair estimate request" for auto, "business loss documentation" for business). Before
that sentence a live run cited only passages. The other graph nodes (35 `BusinessProcess`, 6 `Concept`, such as
`claimref_...` and `cohort_ee`) were extracted from the claim cards, are noise, and are not shown. (The card documents were
deleted on 13 October 2026; the entity count fell from 141 to 93 with them.)

**Twelve more procedures (12 October 2026).** The graph held 9 procedures from our 5 short SOPs, which was thin. With the
owner's approval, `claims.corpus.procedures` (written to a folder by `scripts/build_procedures.py`) authors 12 more, each as ordered
steps with a prerequisite and a responsible role, a stated applicability and a boundary: collision documentation, vehicle
theft verification, home water damage, renters belongings inventory, business downtime evidence, late filing, large loss,
repeat claimant, new policyholder, fraud-flag follow-up, outstanding documents tracking and privacy handling. They are
labelled `hand_authored_synthetic_procedure`, say they are illustrative and not an insurer rule, never decide a claim, and
leave every decision to a human claims handler. Uploaded once each (ledger `ledger.jsonl`); the provider went from 25 to 38
documents (the 38th is Synapt's own episodic document, below), 9 to 21 procedures and 34 to 93 steps. The store check
(`scripts/verify_synapt_store.py`) reads `data/synapt/expected_inventory.json` and then found all 17 procedures and all 20 card
batches (since 13 October it checks the 17 procedures and the ticket store instead; the batches were deleted). The cue logic was run against the live graph for six claim types on 12 October; the offline cases are in
`tests/test_knowledge_graph.py`. One limit: the fraud-flag review signal procedure is in the graph, but no investigation
retrieves it, because the signal is computed after retrieval and so is never a search cue.

### The query agent (`trident_query`): once per investigation and in the side chat (from 12 October 2026)

Synapt's Explainability pages list the answers its query agent writes (the wiki: "every answer is listed with its question,
confidence and outcome", with a Retrieval Pass Card over the knowledge store, context graph, procedure store, fusion and
generation). Reading passages and the graph directly (`trident_get_chunks`, `trident_search`, `trident_traverse`) is
retrieval, not an answer, so on their own those calls never appear there. So that the integration is visible to a Synapt
reviewer, `trident_query` is called in two places, both with `ticket_mode="off"` and `top_k=5`:

1. **Every investigation, once** (`claims.synapt.query_agent`). The question is fixed and built from the claim type alone, plus
   "involving theft" only when the narrative mentions theft: *For an auto claim involving theft, which documents should a
   claims handler request and in what order, who is responsible for each step, and what must a human claims handler review
   before any decision?* The narrative, names, amounts and dates never leave. The call carries the run's ID as `task_id`
   (verified on 12 October: Synapt returns it unchanged), so the entry in Explainability matches the run here; an
   administrator sees the query ID and task ID on the Evidence tab. It runs on its own thread beside the graph lookup and
   the statistics (6.9 s, hidden inside a retrieve stage of 18.9 s), is a span in the live view and the trace, and its answer
   is **display only**: never evidence, never cited, never given to the brief's models, not checked by its validation,
   because it is text a model wrote. A failure leaves one limitation sentence and the brief unchanged. Evaluation runs, the
   interactive search, degraded runs and an adapter without the call make none.
2. **The side chat** (`claims.investigation.sidechat`, "Ask on the side"): only a **handling** question goes there, as the masked question
   plus the claim's type: `Context: an auto claim involving theft. Question: ...`.

Synapt's documentation says it learns from questions it answers ("lived episodes"). Measured on 12 October: right after
several `trident_query` calls on `synapt_capstone1` there was still no episode; the provider had no episode store until the
first `trident_feedback` call, which created `es_synapt_capstone1` (an `episodic` document, one chunk) holding one **lived**
episode tagged `feedback:deflected`, a summary of the investigation question and its answer, anchored on the graph nodes the
answer used. The conclusion drawn that day, that only feedback creates episodes, was wrong: by 13 October the store held 22
lived episodes, all created from the 12 October query-agent sessions. Query sessions do create lived episodes, later and
asynchronously. None is mined yet (see the top of this page).
The owner approved one query per investigation on 12 October. Safeguards: a repeated side question is answered from our saved
answer, a case is limited to 40 side questions and a person to 6 a minute, and a failed call is not saved. A real call measured on 12 October: 5.5 to 6.9 s,
confidence 0.76 to 0.77 (knowledge store 0.80, procedure store 0.87, context graph 0.62), five passages, three procedures, a
reasoning subgraph of about 25 nodes, and a trust signal ("degraded: low-confidence nodes") that the page shows as a note.
Confidence words follow Synapt's own Pass Card scale: 70 and above High (green), 40 to 70 Medium, below 40 Low. Calls made
during development: two on 12 October for the side chat and one for the investigation test, on `synapt_capstone1`.

### Feedback on the query agent's answers (from 12 October 2026)

`trident_feedback` ("record feedback for a query or a specific task") is how Synapt's documented learning loop is fed with a
person's verdict; it created the episode store on 12 October, but it is not the only source of episodes (see above). The owner approved using it on 12 October. Under the
query agent's answer on the Evidence tab, and under a saved knowledge-base answer in the side chat, a handler chooses **Yes, it
helped**, **Partly** or **No**, with an optional note (at most 300 characters). `claims.synapt.query_feedback` maps these to
Synapt's own verdicts `deflected`, `partial` and `not_deflected` and sends `caller_type="user"`.

Safeguards, each pinned by `tests/test_query_feedback.py`:

* The query ID is looked up from the saved run; the request carries only the target (`investigation` or `side:<id>`) and the
  choice, and a request that tries to include a query ID is rejected. A person can therefore rate only an answer that
  belongs to a case they may open.
* The tool has no provider field, so the usual provider scoping cannot apply. The arguments are validated against the
  schema the tenant advertises, and the call must come back `accepted: true`.
* One verdict per answer. Nothing is saved unless Synapt accepted it, so a failed send can be tried again; a second click
  on the same answer is refused. The send is attempted once, never retried automatically.
* The note is masked of personal identifiers before it leaves; the brief, its evidence and its checks are not touched; the
  audit log records the target, the choice and the verdict.
* Only an administrator sees the query ID or Synapt's wording; everyone else sees the plain choice.

An accepted verdict is recorded with a lived episode in Synapt (the test call on 12 October for the investigation question
created episode store `es_synapt_capstone1` with one episode tagged `feedback:deflected`; it was sent as an integration test
and its note says so). The query sessions themselves also become lived episodes, so a verdict is not needed for an episode
to exist. Whether feedback shows in Synapt's Explainability page next to the query was not known when this was written;
the test query's ID is `ced51c0f-30d2-4649-898d-9c490ca8eef5`.

### The Connection page shows what the knowledge base holds (from 12 October 2026)

An administrator sees, on the Connection page, the figures a reviewer would otherwise have to look up in Synapt's console:
documents, passages, graph nodes, connections, procedures, steps, entities, and episodes, with a count of what the graph
extracted by kind. `claims.synapt.stats` reads `trident_get_stats` and `trident_episodes` (its inspect mode lists nothing
and changes nothing), caches the answer for 60 seconds so reloading the page does not call Synapt each time, and the Refresh
button asks again. If Synapt cannot be reached the card says so in a sentence (and keeps the last known figures, marked as
such) rather than showing an error. Endpoint: `GET /api/integration/synapt-stats` (administrators only).

### Why not upload all 100 million claims

* The ingestion tool takes text, about 100 cards per call (31 KB). Each call took two to three
  minutes to embed. 100 million cards would be a million calls: years. (Measured while the claims were
  still uploaded as card documents, until 13 October 2026.)
* Past claims now go into the provider's ticket store through the console's Ticketing source, which
  takes one `.xlsx` workbook (the format itself stops near a million rows, about 1 % of the data). The
  store holds a sample of 2,000 settled claims; a larger upload has not been tried.
* The tool's `database` connector needs a database host that Synapt's cloud can reach; the Parquet file
  is local. It has not been tested.
* Exact counts, shares and medians over the full dataset are arithmetic over rows, which DuckDB does in
  place. Synapt's ticket store finds and labels the nearest tickets to a given ticket.

### Ticket store and `trident_query` (documented 10 October 2026; trialled 12 October 2026; in `synapt_capstone1` from 13 October 2026, see the last paragraph)

The tenant's tool list (read with `tools/list`, no side effects) includes these tools beyond passage search (when this was
first written the application used none of them; what it uses now is noted in each item and at the top of this page):

* `trident_query(provider_id, question, top_k, graph_hops, user_id, task_id, ticket_mode, tickets, label_fields)`. Its
  description says it returns a grounded answer, a confidence score, source chunks, retrieved procedures and graph
  provenance, and, for a provider with a ticket store, per-label confidences with example tickets. Knowledge,
  procedural and graph retrieval always run together; `ticket_mode` is `auto`, `off` or `only`. `only` runs just the
  ticket leg: no question embedding, no graph traversal, no language-model call. `tickets` (at most 50 rows shaped like
  the uploaded dump) are labelled and returned index-aligned in `ticket_labels`. Used now in two ways: `ticket_mode="off"`
  for the query agent's answer, and `ticket_mode="only"` with one ticket per claim for similar past claims.
* `trident_label_ticket(provider_id, ticket, fields)`: finds the most similar already-labelled tickets and ranks what
  they are labelled, returning per field the top candidates with a confidence, the number of neighbours behind each, and an
  example neighbour. It is a nearest-neighbour labeller over the ticket store, not a trained model. Not used.
* `trident_episodes` (read-only; lived and mined episodes) and `trident_feedback` (beta schema `feedback_id`,
  `caller_type`, `verdict`, optional `post_action`, `score`, `reason`; no provider field). Both are now used: see
  [Feedback](#feedback-on-the-query-agents-answers-from-12-october-2026) and the Connection page below.
* Write tools exist too (`trident_create_entity`, `trident_create_concept`, `trident_create_relationship`); the adapter's
  allow-list does not include them.

The console's Ticketing source accepts only `.xlsx` and asks no column questions, so a ticket upload depends on column
names. `scripts/make_ticketing_sample.py` writes a claims-as-tickets workbook (300 rows by default, 2,000 with `--per-type 400 --natural`) for a ticket provider.
A ticket store is a sample (a few hundred to a few thousand rows), not the 100 million claims, so it supplements the
DuckDB search rather than replacing it.

**Trial result (12 October 2026, provider `ticketing_sample`, kind `ticket_mining`, 300 settled claims).** The first
upload was rejected because the workbook's column names were not plain identifiers (`Claim Amount (USD)`); the corrected
names are snake_case, and the second upload became a ticket store. `scripts/ticket_label_trial.py` then labelled 100
settled claims that are not in the workbook (20 per type, 20 flagged), sending only title, description, category and
region with `ticket_mode="only"` (read-only, no language model). Synapt used 48 nearest neighbours per ticket (a fixed
value; `trident_query` has no argument for it) and returned the majority label for every claim:

| Label | Majority baseline | Synapt top label | Minority recall | AUC of minority confidence |
|---|---|---|---|---|
| `resolution` (denied is 21 of 100) | 79 % | 79 % | 0 of 21 | 0.54 |
| `fraud_flag` (flagged is 20 of 100) | 80 % | 80 % | 0 of 20 | 0.58 |

So the store works end to end and its neighbours are sensible (the returned examples are claims of the same type, amount
band and history), but on this data it adds no predictive signal: accuracy equals the always-majority baseline, and
with 20 positives an AUC of 0.54 to 0.58 cannot be told from 0.5. The fraud flag is only weakly predictable even for the
trained model (average precision 0.32 against a 0.077 base rate, [model card](MODEL_CARD.md)), and a 48-neighbour vote
over a 300-ticket store smooths towards the majority. The application therefore does not show a Synapt-predicted outcome
or fraud label. A larger store (2,000 tickets) was tried the same day; see below.

**A 2,000-ticket workbook for the larger test (12 October 2026; uploaded as provider `ticket_mining`, result below).** The owner uploaded it through the console's Ticketing
option. `scripts/make_ticketing_sample.py --per-type 400 --natural --name claims_tickets_2000` writes
`artifacts/synapt/ticketing-2000/claims_tickets_2000.xlsx`: 2,000 settled claims (400 per claim type), the same 16 columns the first
trial's second upload accepted, rows taken in hash order so the fraud flag is **not** over-sampled (105 flagged, 5.3 %; 1,781 approved and
219 denied, 89 % and 11 %). It contains the 300 tickets of the first workbook. Every ticket ID is the card alias, no policy ID appears, and a
read-back found no outcome or label word in the text Synapt embeds (title, description, category, region) and 2,000 distinct descriptions
(`tests/test_ticketing_workbook.py` pins these). Roles to give: ID = `ticket_id`; Embed = `title`, `description`, `category`, `region`;
Predict = `resolution`, `fraud_flag` (or leave the flag as store-only); Store only = the rest. Reviewed handler briefs were considered and
not used: only 2 of the 75 saved investigations have a handler's review, and a label taken from the application's own output would be
circular. After the upload, `scripts/ticket_label_trial.py --provider <id> --workbook-per-type 400 --workbook-natural` labels 100 held-out
settled claims that are not in the workbook, read-only. With 89 % and 95 % majority classes the always-majority baseline is high, so the
result is read against that, as before.

**Result of the 2,000-ticket test (12 October 2026, provider `ticket_mining`, kind `ticket_mining`).** `trident_get_stats` reports 2,000
tickets, 400 of them held out by Synapt itself for scoring, label fields `fraud_flag` and `resolution`, 1,600 labelled each. Synapt's own
held-out accuracy is 95.8 % top-1 for `fraud_flag` and 89.5 % for `resolution`, against workbook majority rates of 94.8 % and 89.1 %, so
within a point or two of always guessing the majority. `scripts/ticket_label_trial.py` (100 held-out claims not in the workbook, 20 %
flagged and 21 % denied by construction, 64 neighbours per ticket now) agrees: the top label was the majority for all 100 claims
(resolution 79 % and fraud flag 80 %, equal to the baselines), 0 of 21 denied and 0 of 20 flagged found, and the AUC of the
minority-class confidence was 0.58 for both (with about 20 positives that cannot be told from 0.5). So at 2,000 tickets the store
still adds no predictive signal on this data, and the application still shows no Synapt-predicted outcome or fraud label. The
provider has no episode store (`trident_episodes` inspect: `exists: false`), so nothing has been mined from the tickets, and whether
mining is a separate console step was not checked. Raw output: `artifacts/synapt/ticketing-2000/label-trial.json`. The first trial's
provider `ticketing_sample` now reports an empty knowledge provider. Both trial providers were throwaway; the application
never read them.

**The ticket store now lives in `synapt_capstone1` (13 October 2026).** The same 2,000 rows, rebuilt as
`artifacts/synapt/ticketing-capstone1/claims_tickets_capstone1.xlsx` (`make_ticketing_sample.py --output
artifacts/synapt/ticketing-capstone1 --per-type 400 --natural --name claims_tickets_capstone1`), were uploaded to the
application's own provider through the console's Ticketing source with the roles above (ID `ticket_id`; Embed `title`,
`description`, `category`, `region`; Predict `resolution`, `fraud_flag`; the rest Store only). The provider's kind became
`ticket_mining` (`has_ticket_store: true`). Synapt held out 400 tickets for its own scoring: top-1 90 % for `resolution`
and 97.25 % for `fraud_flag`, about the majority baseline again. The application uses the store only to find similar past
claims (top of this page) and ignores its labels and confidences, for the reason measured above. Mining is
covered at the top of this page: it has not happened yet.

## Current provider: `synapt_capstone1` (from 9 October 2026)

The application uses `synapt_capstone1`. Since 13 October 2026 its kind is `ticket_mining` (`has_ticket_store: true`).
Verified on 13 October 2026 with `uv run python scripts/verify_synapt_store.py`, which compares the provider with
the committed [`data/synapt/expected_inventory.json`](../data/synapt/expected_inventory.json) using the graph and
`trident_get_stats`:

| Content | Count | Verified by |
|---|---|---|
| Procedures (SOP-AUTO, PROPERTY, BUSINESS, CONFLICT, REVIEW, and the 12 added on 12 October, see the knowledge graph section) | 17 documents, one chunk each | each `source_id` retrieved |
| Synapt's own episodic document `es_synapt_capstone1` | 1 document (22 chunks on 13 October; it grows with use) | created by Synapt; not matched one by one |
| Ticket store (`claims_tickets_capstone1.xlsx`) | 2,000 tickets, 400 held out by Synapt; ID `ticket_id`; labels `fraud_flag`, `resolution` | `trident_get_stats` |

The check prints, among its lines:

```
procedures: 17/17 found by source id
ticket store: 2,000 tickets (400 held out by Synapt), labels fraud_flag, resolution
18 documents in all, 39 chunks: procedures and Synapt's own episode memory
```

and fails if a large document that is not a procedure is left in the provider (a card batch, for example). The inventory
lists no batches and has a `tickets` section with the workbook's rebuild command and hash. `bootstrap.py check` repeats the
comparison on any machine.

**History (9 to 13 October 2026).** The provider was created on 9 October as a knowledge provider populated from
`scripts/build_profile_corpus.py`: the 5 procedures and 20 card batches `profile-0001` to `profile-0020` (501 chunks each:
500 cards and a header chunk, identified by the marker in the header chunk; size and span matched the local batch). That
was 25 documents and 10,025 chunks on 9 October, and nothing else: no probes, test documents or leftovers. On 12 October it
held 38 documents and 10,038 chunks: those 25, the 12 procedures added that day (one document, one chunk each) and Synapt's
own episodic document `es_synapt_capstone1` (one chunk), which its first `trident_feedback` call created. The batches
rebuilt byte for byte from the dataset (20 of 20 hashes matched on a rebuild). The profile sentence on each card
("Profile: N settled claims in the dataset share this description; X% were approved and the median time to settle
was D days.") was read back from Synapt unchanged on 20 of 20 sampled cards, so masking did not alter it. The
application read only the alias from a card; the profile sentence was stored for retrieval and never shown to
a language model. The 20 card documents were deleted in the console on 13 October 2026, after the ticket upload was checked
to leave the documents and the graph unchanged (top of this page).

## Previous provider: `synapt_final_capstone` (to 7 October 2026)

It is untouched and still verifies against `data/synapt/expected_inventory.synapt_final_capstone.json`
(`SYNAPT_PROVIDER_ID=synapt_final_capstone` and `--inventory` that file). The sections below that describe a
provider's contents, its leftovers and its measurements describe this one.

Verified live on 2026-10-07 with `uv run python scripts/verify_synapt_store.py`, which compares the
provider with the committed [`data/synapt/expected_inventory.json`](../data/synapt/expected_inventory.json)
(the same check `bootstrap.py check` runs on any machine). The provider `synapt_final_capstone`
holds **63 documents and 20,914 chunks**, and the application needs nothing more uploaded:

| Documents | Count | Verified by |
|---|---|---|
| Procedures (SOP-AUTO, PROPERTY, BUSINESS, CONFLICT, REVIEW) | 5 | each `source_id` retrieved |
| Base claim-card batches `cards-0001` to `cards-0010` | 10 (1,000 chunks) | size and text length match the local batch (every document is exactly 294 characters longer, Synapt's wrapper) |
| Expansion batches `expanded-0001` to `expanded-0040` | 40 (19,888 chunks for 19,887 cards) | identified by the marker in the header chunk; size and span match the local batch (39 at +1,094 characters, the 387-card batch at +868) |
| Handler lesson | 1 | created while testing the feedback loop |
| Earlier pilot claim card (`CLM-0000000012`, masked) | 1 | superseded; ignored by the application |
| Synapt's own episodic memory of past queries (`doc_type` episodic) | 1 | created by Synapt itself; leave it |
| Parquet schema document (one chunk) | 1 | from the structured-file upload; carries no cards |
| **Test and probe documents** | **4** | see below |

The last five rows (8 documents) and the five procedures hold the remaining 26 chunks, so the totals
add up exactly (1,000 + 19,888 + 26 = 20,914). Those 8 come from the earlier audit and are not matched
one by one by the check. The 100 million source
claims are deliberately not in Synapt. **Do not upload the corpus again:** the tenant exposes no
deletion tool, so duplicates would be permanent, and the ingestion script refuses to run while claim
cards exist. A base corpus rebuilt on another machine is deterministic but is a different sample from
the uploaded one (52 of 1,000 claims coincide), so never compare a local `corpus-v3` with the provider's
content; use the inventory check.

**Clean-up for the console.** Four documents are leftovers of this work and can be deleted in the
Synapt console without effect on the application (they carry no usable identifiers):

1. a first batch of 100 cards whose identifiers were masked (it contains `[ORGANIZATION_…]`
   placeholders and the title "Historical claim cards, batch 0001");
2. "Format probe (synthetic test document; safe to ignore)";
3. "Historical claim cards, PROBE (6 cards)";
4. "State token style probe (synthetic test document; safe to ignore)".

Delete only by recognising the content; the console names files by UUID.

## Findings from the real tenant

### Synapt masks personal-looking text before indexing

A probe document containing a dozen identifier and field formats was ingested and read back:

| Text | Result |
|---|---|
| `CLM-0000000012` (digits) | rewritten as a phone number placeholder |
| `POL-100297760` | rewritten as an SSN placeholder |
| `CLMREF-AAAAAAAABC` (upper-case letters) | survived in one context, rewritten as `[ORGANIZATION_…]` in the card context |
| `clmref-aaaaaaaabc`, `claim_ref_aaaaaaaabc`, `ref.aaaaaaaabc`, a camel-case token | survived intact |
| `Texas`, `Georgia (GA)`, `GA`, `tx` | rewritten as `[LOCATION_…]` |
| `ca` | survived (inconsistent with `tx`) |
| the word `region` before a token | made the whole phrase a location |
| amount bands (`5,000-10,000`), tenure and delay bands, claim-type words | survived intact |

So cards use a **lower-case, letters-only alias** (`CLM-0000000012` becomes `claimref_aaaaaaaabc`,
digits mapped 0-9 to a-j, reversible with no lookup table) and an opaque `regionkey_xx` token in
place of the state. Human-readable text (state names) is used only locally. Both were then verified on
production-format cards (6 of 6 aliases intact), and across the 1,000 uploaded cards.

### Chunking is in tokens, not characters

`chunk_size=500` produced one 2.5 KB chunk from a six-card document; `chunk_size=150` produced four
chunks. The default produced chunks of about 4.5 KB (about 14 cards each). The corpus is ingested
with `chunk_size=100`, which gives about one card per chunk, so a retrieval of 20 chunks returns about
20 distinct cards.

### Reads are capped, so retrieval cannot inventory the store

Measured 2026-10-07 on a store of 20,914 chunks: `trident_get_chunks` returns **at most 1,923 chunks
per query** whatever `top_k` is (3,000, 6,000 and 10,000 all returned 1,923), and a `top_k` of 21,000
fails with a request error (the adapter hides the cause; the failure is immediate, not a timeout). A retrieval inventory is therefore partial, and the old reconciliation
(`top_k = chunks + 100`) fails outright once the store is this size. Looking a card up by its own text is
also unreliable: its chunk came back at rank 1 about half the time, and only about a third of sampled
cards were hit within the top five, for the base cards as much as the expansion ones. **A miss is not
evidence of absence.** Completeness is verified from the graph instead (next sections).

### The graph answers exactly

`trident_cypher` is read-only, requires the `{provider_id: $provider_id}` filter and accepts no
parameters other than `query`, so values must be written into the query. Document nodes carry
`chunk_count`; chunk nodes carry `char_start`, `char_end`, `document_id` and `source_file` but **no
text**. Every chunk returned by `trident_get_chunks` carries its document's `source_file`, so a header
chunk found by its batch marker identifies the document, and the document's chunk count and last
`char_end` can be compared with the local batch. `claims.synapt.inventory` does exactly this.

### Masking also rewrites batch markers

A 9-digit run inside a marker is treated as a US Social Security number: `cardpack_f22102cd4f511272094a`
is stored as `cardpack_f22102cd4f[US_SSN_6a56812069f5]a`, and so is `cardpack_66c6dfe860387495c667`.
Both documents were present and complete; only a literal marker search missed them. The verifier's
`marker_pattern` accepts that rewrite. Avoid long digit runs in any new marker.

### Throughput and cost

A 100-card batch took about three minutes to extract. Entity extraction was negligible (entities
rose from 30 to 38 over 1,000 cards), so cards do not trigger graph extraction.

### The ingestion response carries no request ID

`trident_ingest` returns an object with the keys `accepted`, `connector_type` and `response`; there is no
`req_id`. The adapter therefore treats a response without an error as "submitted" and the caller
checks completion from the provider statistics (document count rising), never from the response.
A response that carries an `error` key is rejected.

### Authentication is rate-limited

The token endpoint returned HTTP 429 after a burst of logins, because the original adapter logged in
again for **every** call. The adapter now keeps one access token (using the server's `expires_in`
when stated, otherwise 4 minutes), logs in again only on expiry or a 401, and waits for `Retry-After`
on a 429. Writes get a 180-second budget instead of 20 seconds.

## Measured semantic precision

(Historical: these measurements are of the claim-card search. The card corpus was removed from `synapt_capstone1` on
13 October 2026; similar claims now come from the ticket store, which names 2 to 4 past claims per lookup and has not been
measured with this protocol. The `verify --sample` commands below need a provider that still holds cards.)

For 60 claims sampled from the uploaded cards, Synapt was asked for the cards most similar to a
card-shaped description of each claim (20 per query). Each returned card was compared with the query
claim:

| Share of returned cards matching the query claim | Synapt | Random pair of cards |
|---|---:|---:|
| Claim type | 33.5% | 20.1% |
| State | 6.8% | 3.9% |
| Amount band | 23.0% | 15.7% |
| Prior-claims band | 35.2% | 34.9% |

Reproduce with `uv run python scripts/synapt_ingest.py verify --sample 60`.

**Reading it honestly.** Synapt's semantic retrieval is a real but mild signal: about 1.7 times chance
on claim type and state, about 1.5 times on amount band, and none on prior claims. Dense embeddings
are weak on numeric attributes, and 1,000 cards of 100 million are a thin sample. Two design
consequences follow, both in [ARCHITECTURE.md](ARCHITECTURE.md): its rank carries half the weight of
the other two signals, and its extra picks are shown separately instead of competing for the top
five. Identity is not tested (many cards share identical descriptors).

### New provider (9 October 2026; historical, card corpus removed on 13 October 2026)

The same protocol on `synapt_capstone1`, while it held the cards: 60 claims sampled from the uploaded cards, 20 cards returned per query,
compared with a random pair of cards from the same corpus
(`SYNAPT_PROVIDER_ID=synapt_capstone1 uv run python scripts/synapt_ingest.py verify --corpus artifacts/synapt/corpus-profile-balanced-2026-10-09 --sample 60`):

| Share of returned cards matching the query claim | New: Synapt | New: random pair | New: times chance | First 1,000 cards: times chance |
|---|---:|---:|---:|---:|
| Claim type | 84.0% | 19.3% | 4.4× | 1.7× |
| State | 20.7% | 3.9% | 5.3× | 1.7× |
| Amount band | 49.4% | 16.5% | 3.0× | 1.5× |
| Prior-claims band | 46.6% | 40.9% | 1.1× | 1.0× |

**Correction (10 October).** The first version of this table (59.9%, 14.2%, 35.0%, 45.5%) was wrong. Each chunk Synapt
returns holds one card **plus the header of the next card** (its body is in the following chunk), and the counting
treated that neighbour as a match, so about half the returned cards were unrelated. Only a card whose `claim_ref:`
body is in the chunk now counts (`claims.corpus.cards.card_ids_in_text`), in both the application and `verify`. The
application's own semantic candidate list had the same noise and is fixed too. The first-corpus column was measured
with the earlier counting and was not re-run, so the comparison is indicative.

**Reading it honestly.** Retrieval is clearly better on the attributes dense embeddings handle well, and still
close to chance on prior claims. This is one run of 60 queries, so treat the multiples as approximate. The two
corpora differ in size (10,000 against 1,000 cards), selection, duplicate rate and card wording, so the gain cannot
be assigned to any one change. As before, each query claim's own card is in the pool, and identity is not tested.

### What the live system does with it

Now (from 13 October 2026): the ticket store names one example neighbour per label value, so a lookup gives 2 to 4 past
claims. Their aliases are decoded and the claims looked up in the Parquet file under the handler's filters; they add a
semantic rank to the DuckDB ranking at half weight and can add up to 3 claims as "related by meaning". In the three live
investigations of 13 October each got 2 to 3 ticket-store claims.

Historical (card search): for the auto-theft demo claim, Synapt matched 55 cards, 25 were eligible under the filters, and
three were added after the five closest as "related by meaning". The five closest were all
California auto claims within $100 of the claim with three prior claims.

## Reliability notes for operators

* Run `uv run python scripts/bootstrap.py check` before a demonstration: it logs in and verifies the
  live provider against `data/synapt/expected_inventory.json` (the 17 procedures, the ticket store's count, ID and
  label fields, and no large non-procedure document left), so it gives the same answer on every machine.
  `scripts/verify_synapt_store.py` runs just that check.
* To describe a changed corpus, rebuild the inventory with
  `uv run python scripts/verify_synapt_store.py --write-expected`; it writes the file only after the
  live provider passes it.
* The local upload ledger (`artifacts/synapt/*/upload-ledger.jsonl`) is not in Git and is no longer
  consulted by the check. `ingest_expanded_cards.py --verify-only` still records graph-verified batches
  in it for the machine that uploaded them.
* Do not upload claim cards into `synapt_capstone1` again: past claims belong in its ticket store, and
  the check fails on a large non-procedure document. The ticket store was filled once through the
  console; a different workbook needs the inventory's `tickets` section rebuilt with it.
* The uploader's own post-submit retrieval check cannot confirm a batch once the store exceeds a few
  thousand chunks (reads are capped, see above).
* `Synapt request failed` almost always means rate limiting or a network blip; wait a minute.
* Synapt is required: there is no non-live mode and the application refuses to start without the Synapt login. If Synapt fails at run time, a clearly labelled **degraded mode** (see [ARCHITECTURE.md](ARCHITECTURE.md)) serves a local copy of the five original procedures and a local semantic index over the 10,000 profile cards (`claim_cards.parquet`, local only; the cards are no longer in Synapt), so a demonstration survives a beta outage. Build the index ahead of time with `uv run python scripts/prepare_fallback_index.py` (about 100 seconds once, then cached) and see how well it retrieves with `--measure`.
* The optional `trident_get_procedures` and `trident_search` calls are off by default
  (`SYNAPT_GRAPH_ENRICHMENT=false`): their responses carry no source passages, so they can never be
  cited, and enabling them only adds calls and a standing warning.
* The ingestion script refuses to start if the provider already contains claim cards, so a second
  machine cannot duplicate a card corpus by accident (`--force` overrides). `synapt_capstone1` holds no
  cards now, so this guard no longer protects it; the rule above does.

## Not verified

* Any console-side Parquet or CSV upload, and a ticket store larger than 2,000 rows. (The console's Ticketing
  `.xlsx` upload and document deletion in the console were used on 12 and 13 October 2026.)
* Episode mining: no mined episode exists yet, and no MCP tool starts it.
* Behaviour at the tenant's quota limits, and per-call cost.
* Whether provider-side deletion of documents is possible from the MCP tools (none is exposed).

## Agents and the Agent Connector (12 October 2026)

Every Synapt call is now made by a named agent and checked against that agent's tool list (`docs/AGENTS.md`): the Policy Passage
Retriever (`trident_get_chunks`, `trident_search`, `trident_get_procedures`, and from 13 October `trident_ticket_neighbours`,
the ticket-only leg of `trident_query`, which lets it find similar past claims but not ask the query agent a question), the
Procedure Graph Navigator (`trident_search`,
`trident_traverse`) and the Knowledge Q&A Agent (`trident_query`). The operator, the ingestion job and the human reviewer are the only
other actors that reach Synapt; only ingestion writes documents and only the reviewer sends feedback.

Synapt's public site and help document do not describe an "Agent Connector" (checked on 12 October). The owner is registering the
three agents above in the console. Until the Connector's authentication scheme is known, per-agent identity is **not** used: the
application reads a client ID per agent (`SYNAPT_AGENT_PASSAGE_RETRIEVER_CLIENT_ID`, `SYNAPT_AGENT_GRAPH_NAVIGATOR_CLIENT_ID`,
`SYNAPT_AGENT_KNOWLEDGE_QA_CLIENT_ID`) and shows an administrator whether each is set, and every call is still made with the one
configured login. Whether the Connector's read-only scope allows `trident_query` (Synapt turns a query session into a lived
episode, asynchronously; see the query agent section) is not yet known.
