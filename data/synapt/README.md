# Expected Synapt inventory

`expected_inventory.json` describes what the Synapt provider `synapt_capstone1` must hold: the 17 procedures
(documents) and the ticket store (2,000 tickets, ID `ticket_id`, label fields `fraud_flag` and `resolution`, from
`claims_tickets_capstone1.xlsx`, rebuilt by the command recorded in the file). It lists no card batches: the 20
claim-card documents were deleted on 13 October 2026, and the check fails if a large non-procedure document is
left behind.

`python scripts/verify_synapt_store.py` (also run by `bootstrap.py check`) compares the live provider with this
file using Synapt's graph and `trident_get_stats`. It works on any machine with the `.env` credentials.

`expected_inventory.synapt_final_capstone.json` is the inventory of the earlier provider (10 base batches of
1,000 cards, 40 expansion batches of 19,887 cards and 5 procedures). Check it with
`--inventory data/synapt/expected_inventory.synapt_final_capstone.json` and `SYNAPT_PROVIDER_ID=synapt_final_capstone`.

How the check works, and why a retrieval-based inventory cannot do this job, is in
[docs/SYNAPT_INTEGRATION.md](../../docs/SYNAPT_INTEGRATION.md). Do not upload claim cards into either provider again.

## Rebuilding on another machine

The ticket workbook is rebuilt by the `rebuild` command recorded in the file's `tickets` section, and its SHA-256 is
recorded (`xlsx_sha256`) so a rebuild can be compared with what was uploaded.

`bootstrap.py corpus` still builds the 10,000 profile cards locally and deterministically (until 13 October 2026, when
they were in Synapt, a rebuild matched all 20 uploaded batch hashes). They are no longer in Synapt; the only thing that
reads them is the degraded-mode fallback, which keeps a local index over `claim_cards.parquet`.
