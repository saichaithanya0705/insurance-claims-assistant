# Expected Synapt inventory

`expected_inventory.json` describes what the Synapt provider `synapt_final_capstone` must hold: the 10
base batches (1,000 cards), the 40 expansion batches (19,887 cards) and the 5 procedures. Each batch
records its name, card count, local text length (`chars`), source-file hash (`sha256`) and, for
expansion batches, the unique marker written in its header.

`uv run python scripts/verify_synapt_store.py` (also run by `bootstrap.py check`) compares the live
provider with this file using Synapt's graph. It works on any machine with the `.env` credentials and
needs no upload ledger, because the ledger lives in `artifacts/`, which is not in Git.

Regenerate the file only when the corpus changes:

`uv run python scripts/verify_synapt_store.py --write-expected` builds the inventory from
`artifacts/synapt/corpus-v3` and `artifacts/synapt/corpus-2026-10-07`, and writes it only if the live
provider passes it.

How the check works, and why a retrieval-based inventory cannot do this job, is in
[docs/SYNAPT_INTEGRATION.md](../../docs/SYNAPT_INTEGRATION.md). Do not upload more into this provider.

## Rebuilding the corpus on another machine

`bootstrap.py corpus` is deterministic: two builds here and a build in a fresh clone selected the same
1,000 claims. It is not the sample that was uploaded, though: only 52 of the uploaded 1,000 claims
coincide; the uploaded batches were most likely produced by an earlier version of the builder, which
Git does not retain. Nothing at runtime
reads the local corpus. The `chars` and `sha256` values above describe the uploaded batches, which exist
only on the original laptop under `artifacts/synapt/corpus-v3` (not in Git).
