# Synapt integration

What Synapt does in this system, what was measured against the real tenant on 2026-10-06, and
what to know before changing it. Commands are in [SETUP.md](SETUP.md). The wire-level contract
(authentication shape, tool names, argument schemas) is in [SYNAPT_CONTRACT.md](SYNAPT_CONTRACT.md).

## Role

| Synapt holds | Used for |
|---|---|
| 5 hand-authored handling procedures (SOPs) | Cited as evidence in findings and recommendations |
| 1,000 historical claim cards, one card per chunk | Semantic ranking of similar claims |
| 19,887 more historical cards (expansion, optional) | The same ranking over a wider pool; the application also works with only the base 1,000 |
| Reviewed handler lessons, ingested when an administrator promotes one | Shared knowledge; also reused locally as cited evidence |

It does **not** hold the 100 million claims. The Parquet file does, and it is the authority for every
filter, every number shown and every model. Synapt returns identifiers, which are looked up in the
Parquet file under the handler's filters.

### Why not upload all 100 million claims

* The ingestion tool takes text, about 100 cards per call (31 KB). Each call took two to three
  minutes to embed. 100 million cards would be a million calls: years.
* The provider is the `knowledge` kind with `has_ticket_store: false`; the tool's `database`
  connector needs a database host that Synapt's cloud can reach.
* The Synapt web console could not be inspected during this work (it needs a login that should not
  be handed to an assistant). If the console accepts a Parquet or CSV upload into a **ticket-store**
  provider, that would be the route to a larger corpus. It has not been tested.

## What is in the provider now

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
cards exist.

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
`char_end` can be compared with the local batch. `claims.synapt_inventory` does exactly this.

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

### What the live system does with it

For the auto-theft demo claim, Synapt matched 55 cards, 25 were eligible under the filters, and
three were added after the five closest as "related by meaning". The five closest were all
California auto claims within $100 of the claim with three prior claims.

## Reliability notes for operators

* Run `uv run python scripts/bootstrap.py check` before a demonstration: it logs in and verifies the
  live provider against `data/synapt/expected_inventory.json` (batches, text spans, procedures), so it
  gives the same answer on every machine. `scripts/verify_synapt_store.py` runs just that check.
* To describe a changed corpus, rebuild the inventory with
  `uv run python scripts/verify_synapt_store.py --write-expected`; it writes the file only after the
  live provider passes it.
* The local upload ledger (`artifacts/synapt/*/upload-ledger.jsonl`) is not in Git and is no longer
  consulted by the check. `ingest_expanded_cards.py --verify-only` still records graph-verified batches
  in it for the machine that uploaded them.
* The uploader's own post-submit retrieval check cannot confirm a batch once the store exceeds a few
  thousand chunks (reads are capped, see above). Do not upload more into this provider; a new corpus
  belongs in a new provider with a new inventory.
* `Synapt request failed` almost always means rate limiting or a network blip; wait a minute.
* Live mode never falls back to fixtures: a Synapt failure fails the investigation visibly.
* The optional `trident_get_procedures` and `trident_search` calls are off by default
  (`SYNAPT_GRAPH_ENRICHMENT=false`): their responses carry no source passages, so they can never be
  cited, and enabling them only adds calls and a standing warning.
* The ingestion script refuses to start if the provider already contains claim cards, so a second
  machine cannot duplicate the corpus by accident (`--force` overrides).

## Not verified

* The Synapt console and any console-side Parquet or CSV upload.
* Behaviour at the tenant's quota limits, and per-call cost.
* Whether provider-side deletion of documents is possible from the MCP tools (none is exposed).
