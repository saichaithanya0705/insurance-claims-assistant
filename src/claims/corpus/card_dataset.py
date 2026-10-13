"""Reproducible, attributed Parquet cards and bounded text exports for Synapt.

The recorded dataset is never augmented with invented incident details. Rich synthetic
evidence belongs to a separate, explicitly authored knowledge pack.
"""

import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

import duckdb

from claims.corpus.builder import DATASET_URL, DISCLAIMER, render_card
from claims.corpus.cards import amount_band, claim_alias, history_band
from claims.history.dataset import COLUMNS, ClaimsStore


def known_claim_ids(root: Path) -> set[str]:
    """Union local manifests/inventories, including uploads performed on other machines."""
    known = set()
    for path in root.rglob("manifest.json"):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for batch in manifest.get("batches", []):
            known.update(batch.get("claim_ids", []))
    for path in root.rglob("inventory.json"):
        known.update(json.loads(path.read_text(encoding="utf-8")).get("claim_ids", []))
    return known


def select_expansion(store: ClaimsStore, *, per_cell: int, cutoff: date, excluded=(), seed=107):
    if not 1 <= per_cell <= 1000:
        raise ValueError("per_cell must be between 1 and 1,000")
    excluded = sorted(set(excluded))
    exclusion = ""
    if excluded:
        exclusion = " AND claim_id NOT IN (" + ",".join("?" for _ in excluded) + ")"
    columns = ",".join(COLUMNS)
    sql = f"""
        SELECT {columns} FROM (
            SELECT {columns}, row_number() OVER (
                PARTITION BY claim_type, state ORDER BY hash(claim_id, ?)
            ) AS rn
            FROM (
                SELECT * FROM {store.source}
                USING SAMPLE reservoir({max(50_000, per_cell * 2000)} ROWS)
                REPEATABLE ({int(seed)})
            ) sampled
            WHERE claim_status IN ('approved','denied')
              AND isfinite(days_to_resolution) AND days_to_resolution >= 0
              AND claim_filed_date + TRY_CAST(floor(days_to_resolution) AS INTEGER) < ?
              {exclusion}
        ) WHERE rn <= ? ORDER BY rn, claim_type, state, claim_id
    """
    return store.rows(sql, [seed, cutoff, *excluded, per_cell])


def write_parquet(records: list[dict], path: Path):
    """DuckDB writes native ZSTD Parquet, then verifies identities and text round-trip."""
    if not records:
        raise ValueError("Cannot export an empty card dataset")
    if path.exists():
        raise ValueError(f"Refusing to overwrite {path}; use a new output directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".jsonl")
    temporary.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
    connection = duckdb.connect()
    connection.execute("SET threads=2")
    connection.execute("SET memory_limit='512MB'")
    try:
        connection.execute("CREATE TEMP TABLE card_export AS SELECT * FROM read_json_auto(?)",
                           [str(temporary)])
        connection.execute(
            "COPY card_export TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(path)],
        )
        result = connection.execute(
            "SELECT count(*), count(DISTINCT claim_ref) FROM read_parquet(?)", [str(path)]
        ).fetchone()
        if result != (len(records), len(records)):
            raise ValueError("Parquet card identity/count validation failed")
        actual = connection.execute(
            "SELECT claim_ref, card_text FROM read_parquet(?) ORDER BY claim_ref", [str(path)]
        ).fetchall()
        expected = sorted((r["claim_ref"], r["card_text"]) for r in records)
        if actual != expected:
            raise ValueError("Parquet card text round-trip failed")
    finally:
        connection.close()
        temporary.unlink(missing_ok=True)


def write_batches(output: Path, records: list[dict], batch_cards: int, prefix: str = "expanded") -> list[dict]:
    """Write ``records`` as marker-headed text batches under ``output/cards`` and describe them."""
    batches = []
    for offset in range(0, len(records), batch_cards):
        group = records[offset:offset + batch_cards]
        number = offset // batch_cards + 1
        marker = "cardpack_" + hashlib.sha256(
            "\n".join(r["claim_ref"] for r in group).encode()
        ).hexdigest()[:20]
        text = (
            f"# Historical claim cards; corpus batch {marker}\n"
            "Source: ZiadataLabs FreeInsuranceClaims100M, CC-BY-NC-4.0. "
            "Derived synthetic tabular records, with no invented narrative or policy wording. "
            f"{DISCLAIMER}\n\n"
        ) + "\n".join(r["card_text"] for r in group)
        data = text.encode("utf-8")
        if len(data) > 900_000:
            raise ValueError("Batch exceeds ingestion text budget")
        name = f"cards/{prefix}-{number:04d}.txt"
        target = output / name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(data)
        batches.append({
            "path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "marker": marker, "cards": len(group),
            "claim_ids": [r["claim_id"] for r in group],
            "sentinels": [group[i]["claim_ref"] for i in sorted({0, len(group)//2, len(group)-1})],
        })
    return batches


def build_card_dataset(store: ClaimsStore, output: Path, *, per_cell=100,
                       cutoff=date(2026, 1, 1), excluded=(), batch_cards=500, seed=107):
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output must be empty; use a new directory for a new corpus")
    if not 1 <= batch_cards <= 1000:
        raise ValueError("batch_cards must be between 1 and 1,000")
    rows = select_expansion(store, per_cell=per_cell, cutoff=cutoff, excluded=excluded, seed=seed)
    records = []
    for row in rows:
        # Fraud labels and policy identifiers remain in the original source, not retrieval context.
        fields = {key: value for key, value in row.items()
                  if key not in {"policy_id", "is_fraud_flagged_ground_truth"}}
        records.append(fields | {
            "claim_ref": claim_alias(row["claim_id"]),
            "card_text": render_card(row),
            "amount_band": amount_band(row["claim_amount"]),
            "history_band": history_band(row["previous_claims_count"]),
            "source_url": DATASET_URL,
            "provenance": "published_synthetic_tabular_record",
            "license": "CC-BY-NC-4.0",
            "historical_cutoff_exclusive": cutoff.isoformat(),
            "has_incident_narrative": False,
            "has_policy_wording": False,
        })
    output.mkdir(parents=True, exist_ok=True)
    parquet = output / "claim_cards.parquet"
    write_parquet(records, parquet)
    batches = write_batches(output, records, batch_cards)
    counts = Counter((r["claim_type"], r["state"]) for r in records)
    manifest = {
        "schema_version": 3, "cards": len(records), "batches": batches, "procedures": [],
        "parquet": {"path": parquet.name, "bytes": parquet.stat().st_size,
                    "sha256": hashlib.sha256(parquet.read_bytes()).hexdigest()},
        "source": store.fingerprint() | {"url": DATASET_URL, "license": "CC-BY-NC-4.0"},
        "selection": {"per_type_state": per_cell, "seed": seed,
                      "cutoff_exclusive": cutoff.isoformat(), "excluded_known_ids": len(set(excluded)),
                      "rule": "repeatable reservoir candidate pool; closed before cutoff, "
                              "hash-ordered within type and state",
                      "candidate_sample_rows": max(50_000, per_cell * 2000)},
        "cards_by_type": dict(Counter(r["claim_type"] for r in records)),
        "cards_by_type_state": {f"{k[0]}:{k[1]}": n for k, n in sorted(counts.items())},
        "amount_bands": dict(Counter(r["amount_band"] for r in records)),
        "history_bands": dict(Counter(r["history_band"] for r in records)),
        "excluded": ["policy_id", "is_fraud_flagged_ground_truth"],
        "source_boundary": "No incident narratives, policy terms or rejection reasons are invented",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
