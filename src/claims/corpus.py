"""Build the Synapt knowledge corpus from the full Parquet dataset.

Synapt cannot hold 100 million claims through its text-ingestion tool (a few dozen cards per call,
each call extracted by a model). The corpus is therefore a deterministic, stratified subset of
historical claim *cards*, plus the handling procedures. The Parquet file remains the authoritative
source for filters, statistics and every number shown to the handler; Synapt supplies semantic
ranking and procedures. Nothing here uploads anything: ``scripts/synapt_ingest.py`` does that.
"""

import hashlib
import json
from datetime import date
from pathlib import Path

from claims.cards import claim_alias, claim_card_text
from claims.dataset import COLUMNS, ClaimsStore

DATASET_URL = "https://huggingface.co/datasets/ziadatalabs/FreeInsuranceClaims100M"
ATTRIBUTION = "ZiadataLabs - FreeInsuranceClaims100M; CC BY-NC 4.0"
CLAIM_TYPES = ("auto", "business", "home", "property", "renters")
MAX_BATCH_CARDS = 100
MAX_BATCH_BYTES = 60 * 1024
DISCLAIMER = (
    "Educational decision support only. A card does not decide coverage, approve or deny a claim, "
    "authorize payment, or establish fraud. A human claims handler must review evidence and "
    "applicable policy terms."
)
SOPS = (
    (
        "SOP-AUTO-001",
        "Synthetic auto documentation and theft procedure",
        (
            "For an auto claim, request an incident statement and repair estimate; for theft, request"
            " a police report when applicable. Confirm the document's relevance with the handler. "
            "Record which documents were supplied and which remain outstanding. A document name in an"
            " intake form records availability, not verified contents or authenticity. This is an "
            "illustrative training procedure, not an insurer rule or policy requirement."
        ),
    ),
    (
        "SOP-PROPERTY-001",
        "Synthetic property and renters documentation procedure",
        (
            "For home or property claims, request an incident statement, damage photographs and a "
            "damage assessment supported by an itemized repair estimate. For renters claims, request "
            "an incident statement and an inventory list of damaged or lost items. Confirm "
            "applicability and ownership with the handler. Ask a focused question when an item, date "
            "or amount is unclear. This is an illustrative training procedure, not an insurer rule or"
            " policy requirement."
        ),
    ),
    (
        "SOP-BUSINESS-001",
        "Synthetic business loss documentation procedure",
        (
            "For business claims, request an incident statement and a loss assessment supported by "
            "loss documentation, such as an itemized asset list or the relevant accounting records. "
            "Separate submitted estimates from documented amounts. Ask the handler which evidence is "
            "applicable before requesting additional material. Business interruption coverage cannot "
            "be inferred from a business claim label. This is an illustrative training procedure, not"
            " an insurer rule or policy requirement."
        ),
    ),
    (
        "SOP-CONFLICT-001",
        "Synthetic conflicting evidence reconciliation procedure",
        (
            "When two supplied sources state different dates, amounts or incident details, preserve "
            "both statements and their source identifiers. Quote the relevant passages accurately. "
            "Check whether the statements refer to the same event and whether one is a correction. "
            "Request focused clarification from the handler. Do not silently replace a conflicting "
            "fact or treat missing information as a contradiction. A difference between two "
            "historical claims is not itself contradictory evidence. This is an illustrative training"
            " procedure."
        ),
    ),
    (
        "SOP-REVIEW-001",
        "Synthetic coverage and human review boundary",
        (
            "Check the actual policy version, applicable wording and endorsements with the handler "
            "before assessing coverage. A historical approved or denied status does not explain the "
            "decision and does not bind a new claim. Numerical similarity is a comparison signal, not"
            " a probability of approval. A fraud-risk estimate is an investigation signal, not proof "
            "or an accusation. If policy terms or supporting evidence are unavailable, state the "
            "limitation and request handler review. Final decisions and external actions require "
            "human authorization. This is an illustrative training procedure, not legal advice."
        ),
    ),
)


def select_cards(store: ClaimsStore, per_type: int, cutoff: date, seed: int = 42) -> list[dict]:
    """Deterministic stratified subset: ``per_type`` settled claims of each claim type.

    Only approved/denied claims closed strictly before ``cutoff`` qualify, so every card describes
    an outcome that was already known. Fraud labels are never selected.
    """
    if not 1 <= per_type <= 100_000:
        raise ValueError("per_type must be between 1 and 100,000")
    # A hash filter keeps the window sort small: it keeps threshold/10,000 of all rows, sized to
    # leave ~20x the cards needed (more than enough for the rarest type) without sorting 100M rows.
    needed = per_type * len(CLAIM_TYPES) * 20
    threshold = min(10_000, max(1, -(-needed * 10_000 // store.row_count())))
    columns = ", ".join(COLUMNS)
    sql = f"""
        SELECT {columns} FROM (
            SELECT {columns},
                   row_number() OVER (PARTITION BY claim_type ORDER BY hash(claim_id, ?)) AS rn
            FROM {store.source}
            WHERE claim_status IN ('approved', 'denied')
              AND claim_filed_date + TRY_CAST(floor(days_to_resolution) AS INTEGER) < ?
              AND hash(claim_id, ?) % 10000 < ?
        ) WHERE rn <= ? ORDER BY claim_id
    """
    rows = store.rows(sql, [seed, cutoff, seed, threshold, per_type])
    counts = {kind: sum(r["claim_type"] == kind for r in rows) for kind in CLAIM_TYPES}
    short = [kind for kind, n in counts.items() if n < per_type]
    if short:
        raise ValueError(
            f"Not enough eligible claims for {short} at this sample fraction; "
            "lower per_type or pick a later cutoff"
        )
    return rows


def render_card(row: dict) -> str:
    alias = claim_alias(row["claim_id"])
    return f"## history:{alias}\nclaim_ref: {alias}\n{claim_card_text(row, masking_safe=True)}\n"


def batch_header(number: int, count: int) -> str:
    return (
        f"# Historical claim cards, batch {number:04d} ({count} cards)\n"
        "Source: published free synthetic insurance claims dataset (CC BY-NC 4.0). "
        "Synthetic tabular records: no incident narrative, policy wording "
        "or fraud label is included, and every card is derived only from structured fields. "
        f"{DISCLAIMER}\n\n"
    )


def make_batches(cards: list[tuple[dict, str]], max_cards: int, max_bytes: int) -> list[list]:
    if not 1 <= max_cards <= MAX_BATCH_CARDS or not 1024 <= max_bytes <= MAX_BATCH_BYTES:
        raise ValueError("Batch limits must be 1..100 cards and 1,024..61,440 UTF-8 bytes")
    reserve = len(batch_header(9999, max_cards).encode("utf-8"))
    batches, current, size = [], [], reserve
    for row, text in cards:
        length = len(text.encode("utf-8")) + 1
        if reserve + length > max_bytes:
            raise ValueError("A single card exceeds the batch byte limit")
        if current and (len(current) >= max_cards or size + length > max_bytes):
            batches.append(current)
            current, size = [], reserve
        current.append((row, text))
        size += length
    if current:
        batches.append(current)
    return batches


def sop_document(source_id: str, title: str, body: str) -> str:
    return (
        f"# {title}\nsource_id: {source_id}\nprovenance: hand_authored_synthetic_procedure\n"
        f"attribution: Synapt Claims Investigator project - illustrative educational example\n"
        f"{DISCLAIMER}\n\n{body}\n"
    )


def build_corpus(
    store: ClaimsStore,
    output: Path,
    *,
    per_type: int = 200,
    cutoff: date = date(2026, 1, 1),
    seed: int = 42,
    max_cards: int = MAX_BATCH_CARDS,
    max_bytes: int = MAX_BATCH_BYTES,
) -> dict:
    """Write batch files and a manifest under ``output``; refuse to overwrite different content."""
    rows = select_cards(store, per_type, cutoff, seed)
    cards = [(row, render_card(row)) for row in rows]
    files = {}
    batches = make_batches(cards, max_cards, max_bytes)
    records = []
    for number, batch in enumerate(batches, start=1):
        text = batch_header(number, len(batch)) + "\n".join(card for _, card in batch)
        name = f"cards/cards-{number:04d}.txt"
        files[name] = text
        records.append(
            {
                "path": name,
                "bytes": len(text.encode("utf-8")),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "claim_ids": [row["claim_id"] for row, _ in batch],
            }
        )
    for source_id, title, body in SOPS:
        text = sop_document(source_id, title, body)
        name = f"procedures/{source_id.lower()}.txt"
        files[name] = text
    manifest = {
        "schema_version": 2,
        "source": store.fingerprint() | {"url": DATASET_URL, "license": "CC-BY-NC-4.0"},
        "selection": {
            "per_type": per_type,
            "cutoff_exclusive": cutoff.isoformat(),
            "seed": seed,
            "rule": "approved/denied claims closed before the cutoff; hash-ordered within type",
        },
        "cards": len(cards),
        "cards_by_type": {k: sum(r["claim_type"] == k for r in rows) for k in CLAIM_TYPES},
        "batches": records,
        "procedures": sorted(p for p in files if p.startswith("procedures/")),
        "excluded": ["is_fraud_flagged_ground_truth", "policy_id", "numeric claim identifiers"],
        "id_scheme": "CLM-0000000012 -> claimref_aaaaaaaabc (digits a-j); state -> regionkey_xx, "
        "both chosen to survive Synapt PII masking",
    }
    files["manifest.json"] = json.dumps(manifest, indent=2) + "\n"
    for name, text in files.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != text.encode("utf-8"):
            raise ValueError(f"Conflicting content already exists at {path}; use a new directory")
        path.write_bytes(text.encode("utf-8"))
    return manifest
