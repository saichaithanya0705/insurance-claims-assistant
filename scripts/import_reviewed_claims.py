"""Import original intake snapshots and separate human label evidence as Parquet.

uv run python scripts/import_reviewed_claims.py --csv claims.csv --evidence adjudications.json \
  --source-id reviewed_insurer_v1 --source-url https://example.org/dataset --license internal-permission \
  --domain us_auto --output data/processed/ml/richer/reviewed_insurer_v1
"""

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from claims.fraud_features import file_digest, rows_digest
from claims.reviewed_claims import reviewed_records
from claims.richer_data import parse_csv, production_blockers, write_parquet


def import_reviewed(csv_path, evidence_path, output, source_id, source_url, license_name, domain):
    if not re.fullmatch(r"reviewed_[a-z0-9_]{1,60}", source_id):
        raise ValueError("Use a versioned reviewed_ source ID")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new empty directory for each reviewed source version")
    columns, raw = parse_csv(csv_path.read_bytes())
    evidence_bytes = evidence_path.read_bytes()
    evidence = json.loads(evidence_bytes)
    rows, audit = reviewed_records(raw, evidence, source_id)
    if not rows:
        raise ValueError(f"No admissible evidence-backed records: {audit}")
    output.mkdir(parents=True, exist_ok=True)
    (output / "original.csv").write_bytes(csv_path.read_bytes())
    (output / "adjudications.json").write_bytes(evidence_bytes)
    write_parquet(rows, output / "claims.parquet")
    manifest = {
        "schema_version": 1,
        "adapter": "reviewed_v1",
        "source_id": source_id,
        "source_url": source_url,
        "license": license_name,
        "domain": domain,
        "downloaded_at": datetime.now(UTC).isoformat(),
        "origin": "user_supplied_source_and_human_adjudications",
        "label_verification": "supplied_human_evidence_cross_checked",
        "feature_availability": "intake_snapshot_timestamps_cross_checked",
        "benchmark_eligible": True,
        "raw_csv": "original.csv",
        "raw_csv_sha256": file_digest(output / "original.csv"),
        "source_columns": columns,
        "evidence": "adjudications.json",
        "evidence_sha256": file_digest(output / "adjudications.json"),
        "parquet": "claims.parquet",
        "parquet_sha256": file_digest(output / "claims.parquet"),
        "rows_sha256": rows_digest(rows),
        "audit": audit,
        "positives": sum(r["is_fraud"] for r in rows),
    }
    manifest["production_blockers"] = production_blockers(manifest, rows)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--license", required=True)
    parser.add_argument("--domain", choices=["us_auto", "us_property_and_casualty"], required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            import_reviewed(
                args.csv,
                args.evidence,
                args.output,
                args.source_id,
                args.source_url,
                args.license,
                args.domain,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
