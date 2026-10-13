# Which claims go into Synapt: measured analysis and the profile corpus (9 October 2026)

**Status: historical. The card corpus described here was removed from Synapt on 13 October 2026**; past claims are now
2,000 settled claims in the ticket store of `synapt_capstone1`, and its documents hold the 17 procedures (see
[Superseded on 13 October](#superseded-on-13-october-the-claims-moved-to-the-ticket-store) and
[SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md#how-the-data-is-split-across-synapt-corrected-13-october-2026)). From 9 to
13 October the corpus was built, uploaded and verified in `synapt_capstone1`; the cards now exist only as the local
degraded-mode fallback index. The older provider `synapt_final_capstone` is unchanged. Re-run the analysis with
`uv run python scripts/analyze_card_coverage.py` (read-only, about 20 seconds).

## What the old provider holds

`synapt_final_capstone` holds 20,887 claim cards: a 1,000-card first batch and a 19,887-card expansion chosen as
**claim type × state groups, random within each group** (seeded, settled before a cutoff, deduplicated against
the first batch; see [DATA_EXPANSION_2026-10-07.md](DATA_EXPANSION_2026-10-07.md)). The rule that picked the first
1,000 was an earlier builder version that Git does not retain ([SETUP.md](SETUP.md)), so only the expansion's rule
is reproducible.

## The finding

A card describes a claim only through bands: claim type, state, amount band, tenure band, prior-claims band and
filing-delay band. A query to Synapt never states an outcome, so two claims with the same bands are the same
description, and a card that repeats an existing description adds nothing for semantic retrieval.

Among the 72,237,338 settled claims closed before 2026-01-01 there are only **110,093 distinct descriptions**.
They are very unevenly populated: the median description covers 93 claims, but the most common 1% of descriptions
hold 22% of all claims.

For a given number of cards, how likely is it that a *new* claim has an exact-description twin among them?
(Exact expectations from the per-description counts, not random draws.)

| Cards | Random sample | Type × state groups (the expansion rule) | One card per description, most common first |
|---:|---:|---:|---:|
| 1,000 | 7.7% | 3.6% | 21.1% |
| 2,500 | 16.6% | 8.7% | 35.0% |
| 5,000 | 27.4% | 16.3% | 49.1% |
| 10,000 | 41.4% | 28.8% | **65.6%** |
| 20,887 | 57.7% | 47.4% | **83.4%** |

* A random sample of 20,887 repeats an existing description for 8,034 cards (38%). Volume-first repeats none.
* Equal allocation to every type × state group is **worse** than plain random on this measure, because it gives
  small groups as many cards as the largest ones.
* 10,000 volume-first cards (65.6%) beat 20,887 random cards (57.7%) with half the cards, and so half the
  ingestion time.

**What this does and does not show.** It compares selection *rules*. The old provider's real composition cannot be
measured from this machine, because the expansion manifest and the uploaded first batches are not here. An exact
twin is a proxy: semantic search finds near neighbours, so the real test is the retrieval check below.

## Is it enough for each category?

Ranking all descriptions together is not enough, and the measurement shows it. With 10,000 globally ranked cards,
coverage by claim type is auto 77.7%, home 70.0%, renters 55.4%, property 55.3% and **business 42.9%**, because each
business description holds fewer claims and so ranks lower. Giving every claim type its own most-common-first
ranking and **2,000 cards each** costs 2.6 points overall (63.0% against 65.6%) and makes every category even:

| Claim type | Cards | Eligible claims | Claims whose exact description has a card |
|---|---:|---:|---:|
| auto | 2,000 | 25,278,726 | 62.8% |
| business | 2,000 | 7,225,008 | 62.9% |
| home | 2,000 | 18,059,252 | 63.6% |
| property | 2,000 | 10,838,916 | 62.6% |
| renters | 2,000 | 10,835,436 | 62.6% |
| **all** | **10,000** | **72,237,338** | **63.0%** (45,482,907 claims) |

## The profile corpus

1. **Eligibility:** settled (approved or denied) and closed strictly before the cutoff, so every card describes an
   outcome that was already known. No fraud flag and no policy ID ever leave the dataset.
2. **One card per distinct description, most common first within each claim type**, 2,000 per type. No card repeats
   another. The smallest group a card summarises still holds 942 claims.
3. **Each card describes one real exemplar claim**, chosen deterministically (smallest `hash(claim_id, seed)` in the
   description), with the same masking-safe alias as every other card, so the application's existing path (Synapt
   returns an alias, the application decodes it and reads the claim from Parquet) is unchanged.
4. **First corpus only: each card also stated what its whole group looks like** (how many claims share the
   description, the share approved, the median days to settle). That sentence, and the outcome sentence before it,
   lowered retrieval and are not read by the application; the next corpus drops both (see the 10 October finding below).
   The wording never said a claim is covered, valid or eligible.
5. **Built by** `scripts/build_profile_corpus.py` (module `claims.corpus.profile_cards`, tests in
   `tests/test_profile_cards.py`). Output: 20 batches of 500 cards, the five procedures, a Parquet file and a manifest
   whose `coverage` section records the measured figures above. The build is deterministic.
6. **A new, empty provider** (`synapt_capstone1`), because the old one cannot be cleaned (no deletion tool is
   exposed) and the uploader refuses to add cards to a provider that already holds them.

Because the order is most-common-first, the corpus can be extended later without deleting anything: more cards for
any type are simply the next most common descriptions.

## Measured retrieval quality

`synapt_ingest.py verify` on `synapt_capstone1` (60 claims, 20 cards each), against the same protocol on the first
1,000-card corpus: claim type 4.4× chance (was 1.7×), state 5.3× (was 1.7×), amount band 3.0× (was 1.5×),
prior-claims band 1.1× (was 1.0×). These are the corrected figures: the first version of this paragraph counted the
neighbouring card in each returned chunk (see the correction in [SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md)).

## Finding of 10 October: the profile sentence lowers retrieval

The same local embedding model, the same 60 claims and 20 returned cards (`scripts/prepare_fallback_index.py --measure`),
three card text formats. Share of returned cards matching the query claim (chance in brackets):

| Card text that is embedded | Claim type | State | Amount band | Prior claims |
|---|---:|---:|---:|---:|
| Description only | 100% (20%) | 95.5% (4.6%) | 62.3% (14.0%) | 63.6% (38.9%) |
| Description + outcome sentence | 100% | 91.2% | 57.3% | 58.3% |
| Description + outcome + profile sentence (the cards in Synapt) | 100% | 66.0% | 47.5% | 46.2% |

A query never states an outcome or a profile, so extra sentences only dilute the match. The application reads nothing from
them (the outcome and statistics come from the dataset by claim ID), so they cost retrieval quality for no benefit. This
was measured with a local model, not Synapt's, so the size of the effect in Synapt is unproven; Synapt's own figures on
the current cards are 84% / 21% / 49% / 47%. A re-upload should use description-only cards.

## The next corpus: description-only cards, balanced order

`scripts/build_profile_corpus.py` now defaults to `--card-format description` (header, `claim_ref` and the description a
query can state; no outcome, no group profile) and `--order balanced`. The same 10,000 descriptions and exemplar claims
are selected, so coverage is unchanged (63.0% of eligible claims have an exact-description twin); only the text and the
batch order differ. `--card-format profile --order common_first` reproduces the first corpus.

Balanced order round-robins over (claim type, state), each in most-common-first order. With most-common-first the first
500 cards came from 13 states (CA, TX and FL alone held 381), so a 500-card pilot would have exercised a third of the
region tokens; balanced, the same 500 span all 38 states and all five claim types, and a partly uploaded corpus stays
representative. Every card is read back from Synapt and compared with the local text (`scripts/audit_card_readback.py`),
because the graph check cannot see masking.

## Superseded on 13 October: the claims moved to the ticket store

The card corpus described in this document is no longer in Synapt. Claim records are cases with outcomes, which belong in Synapt's ticket store, not in the documents the knowledge graph is built from; the 20 card documents made up 99.6 % of the provider's chunks and added almost nothing to the graph. The provider now holds the 17 procedures as documents and 2,000 settled claims as tickets. See "How the data is split across Synapt" in [SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md). The card builders and the local fallback index stay in the repository; the analysis in this document is kept as the record of how the cards were chosen.

## Decision of 10 October: `synapt_capstone1` stays the production provider

*The provider is still the one in use, but its card corpus was superseded on 13 October (section above).*

The description-only corpus (`artifacts/synapt/corpus-description-balanced-2026-10-10`) is built and tested locally, and
a pilot was submitted to `synapt_final_capstone1`, but Synapt's ingestion pipeline stalled that day (documents stopped at
Normalize or Chunk for hours, nothing extracted). The owner decided to keep `synapt_capstone1` as the original and final
corpus:

* its 25 documents (10,025 chunks) are extracted and verified from the graph (38 and 10,038 since 12 October, after 12
  hand-authored procedures and Synapt's own episode document were added; the cards are unchanged);
* only about 2.4% of cards have a rewritten state token, which has little effect because state filtering and weighting
  happen locally from Parquet;
* its whole cards keep the outcome and the group profile (size, approval share, median days) that `trident_query` can
  quote with sources, which description-only cards would remove.

What this trades away: the local test says description-only cards retrieve better (see above), and that has not been
measured in Synapt itself. Two cautions on using the profile sentence: it says "settled claims in the dataset" but counts
claims settled before 2026, and it comes from the 20 nearest cards, so it is an approximate cohort, not the exact cohort
DuckDB can compute for a filter. The new corpus stays in the repository as a documented, ready alternative.

## Not claimed

* That the gain comes from the selection rule alone. The new corpus differs from the old in size, duplicate rate and
  card wording, and only one run of 60 queries has been made.
* That the application used the profile sentence. It was stored in Synapt with each card until 13 October. The application read
  only the alias from a card, and no profile statistic reached a language model; see "No coverage conclusions" in
  [ARCHITECTURE.md](ARCHITECTURE.md) before changing that.
* Anything about real insurers: the data is synthetic and licensed CC BY-NC 4.0.

## Checklist

- [x] Descriptor-space analysis (`scripts/analyze_card_coverage.py`)
- [x] Builder for the profile corpus, with tests
- [x] New empty provider `synapt_capstone1` created and confirmed empty
- [x] Five procedures uploaded
- [x] Pilot batch (500 cards) verified, and the profile sentence checked for masking (20 of 20 intact)
- [x] Remaining 19 batches uploaded; 20 of 20 batches verified from Synapt's graph
- [x] Retrieval precision measured on the new provider
- [x] Application switched to the new provider (`.env`, inventory)
- [x] 13 October 2026: 2,000 settled claims uploaded to the provider's ticket store and the 20 card documents deleted;
  the card corpus above is no longer in Synapt
