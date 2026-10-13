"""Download original public sources, audit them, and preserve them as Parquet.

Run: uv run python scripts/prepare_richer_claims.py
No source notebook is executed; labels and missing timestamps are never invented.
"""

import argparse
import hashlib
import io
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from claims.ml.fraud_features import file_digest, rows_digest
from claims.ml.richer_data import (
    EXPECTED_MENDELEY_COLUMNS,
    KAGGLE_ID,
    MENDELEY_ID,
    normalize_records,
    parse_csv,
    production_blockers,
    verified_records,
    write_parquet,
)

MENDELEY_PAGE = "https://data.mendeley.com/datasets/992mh7dk9y/2"
MENDELEY_FILES = (
    "https://data.mendeley.com/public-api/datasets/992mh7dk9y/files?folder_id=root&version=2"
)
KAGGLE_PAGE = (
    "https://www.kaggle.com/datasets/mmumairkhattak/insurance-claims-dataset-2026-fd-and-ra"
)
KAGGLE_DOWNLOAD = "https://www.kaggle.com/api/v1/datasets/download/mmumairkhattak/insurance-claims-dataset-2026-fd-and-ra"
MAX_BYTES = 20 * 1024 * 1024


def download(client, url):
    with client.stream("GET", url) as response:
        response.raise_for_status()
        data = bytearray()
        for block in response.iter_bytes():
            data.extend(block)
            if len(data) > MAX_BYTES:
                raise ValueError("Public source exceeds bounded download size")
        return bytes(data)


def store_immutable(path, data):
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Original source changed; use a new version directory: {path}")
        return
    path.write_bytes(data)


def prepare_mendeley(client, output):
    output.mkdir(parents=True, exist_ok=True)
    if (output / "manifest.json").exists():
        manifest, _ = verified_records(output / "manifest.json")
        return manifest
    files = json.loads(download(client, MENDELEY_FILES))
    choices = [f for f in files if f.get("filename") == "insurance_claims.csv"]
    if len(choices) != 1:
        raise ValueError("Expected exactly one original Mendeley CSV")
    entry = choices[0]
    details = entry["content_details"]
    url = details["download_url"]
    if not url.startswith("https://data.mendeley.com/public-files/datasets/992mh7dk9y/files/"):
        raise ValueError("Unexpected original download host/path")
    data = download(client, url)
    if len(data) != details["size"] or hashlib.sha256(data).hexdigest() != details["sha256_hash"]:
        raise ValueError("CSV does not match publisher checksum and size")
    store_immutable(output / "insurance_claims.csv", data)
    if not (output / "source_page.html").exists():
        store_immutable(output / "source_page.html", download(client, MENDELEY_PAGE))
    (output / "source_file_metadata.json").write_text(json.dumps(entry, indent=2), encoding="utf-8")
    columns, raw = parse_csv(data)
    if not EXPECTED_MENDELEY_COLUMNS <= set(columns):
        raise ValueError("Required original richer-claim fields are absent")
    rows, audit = normalize_records(raw)
    parquet = output / "claims.parquet"
    write_parquet(rows, parquet)
    manifest = {
        "schema_version": 1,
        "source_id": MENDELEY_ID,
        "source_url": MENDELEY_PAGE,
        "version": "2",
        "license": "CC-BY-4.0",
        "attribution": "ABDELRAHIM AQQAD (2023), insurance_claims, Mendeley Data v2, doi:10.17632/992mh7dk9y.2",
        "downloaded_at": datetime.now(UTC).isoformat(),
        "domain": "us_auto",
        "origin": "publisher_claims_insurer_origin_unverified",
        "label_verification": "publisher_binary_annotation",
        "feature_availability": "unverified",
        "benchmark_eligible": True,
        "raw_csv": "insurance_claims.csv",
        "raw_csv_sha256": file_digest(output / "insurance_claims.csv"),
        "publisher_sha256_verified": True,
        "source_columns": columns,
        "parquet": "claims.parquet",
        "parquet_sha256": file_digest(parquet),
        "rows_sha256": rows_digest(rows),
        "audit": audit,
        "positives": sum(r["is_fraud"] for r in rows),
        "missing_features": {key: sum(r.get(key) is None for r in rows) for key in rows[0]},
        "excluded_model_fields": [
            "fraud_reported",
            "claim_id",
            "policy_id",
            "source_row",
            "raw_row_sha256",
            "age",
            "insured_sex",
            "insured_zip",
            "insured_hobbies",
            "insured_occupation",
            "insured_relationship",
            "incident_location",
            "incident_city",
            "_c39",
            "injury_claim",
            "property_claim",
            "vehicle_claim",
        ],
    }
    manifest["production_blockers"] = production_blockers(manifest, rows)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def audit_kaggle(client, output):
    output.mkdir(parents=True, exist_ok=True)
    if (output / "audit.json").exists():
        report = json.loads((output / "audit.json").read_text(encoding="utf-8"))
        for filename, key in (
            ("original.zip", "archive_sha256"),
            ("insurance_claims_dataset.csv", "csv_sha256"),
            ("original_records.parquet", "parquet_sha256"),
        ):
            if file_digest(output / filename) != report[key]:
                raise ValueError("Previously staged source differs from its audit")
        return report
    data = download(client, KAGGLE_DOWNLOAD)
    archive_path = output / "original.zip"
    store_immutable(archive_path, data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(f.file_size for f in archive.infolist()) > MAX_BYTES:
            raise ValueError("Uncompressed dataset exceeds bounded size")
        required = "insurance_claims_dataset.csv"
        csv_data = archive.read(required)
        store_immutable(output / required, csv_data)
        dictionary = archive.read("data_dictionary.csv")
        store_immutable(output / "data_dictionary.csv", dictionary)
        notebook = json.loads(archive.read("insurance_claims_notebook.ipynb"))
    columns, rows = parse_csv(csv_data)
    # Preserve original values as a separate raw staging table, never pool with approved claims.
    write_parquet(rows, output / "original_records.parquet")
    cells = ["".join(c.get("source", [])) for c in notebook.get("cells", [])]
    relevant = [
        c
        for c in cells
        if any(token in c for token in ("Fraud_Flag", "Fraud_Risk_Score", "random", "synthetic"))
    ]
    (output / "notebook_source_review.json").write_text(
        json.dumps(relevant, indent=2), encoding="utf-8"
    )
    reasons = [
        "No incident/filing dates or label observation times",
        "No incident severity, vehicle, injury or witness fields",
        "Downloaded dictionary only repeats column names; feature provenance is undocumented",
        "Fraud_Risk_Score, Claim_Status and Settlement_Amount must not be fraud-model inputs",
    ]
    if len(columns) != 40:
        reasons.append(
            f"Downloaded schema has {len(columns)} columns; public description advertised 40"
        )
    report = {
        "source_id": KAGGLE_ID,
        "source_url": KAGGLE_PAGE,
        "license_as_published": "MIT",
        "downloaded_at": datetime.now(UTC).isoformat(),
        "rows": len(rows),
        "columns": columns,
        "archive_sha256": file_digest(archive_path),
        "csv_sha256": file_digest(output / required),
        "parquet_sha256": file_digest(output / "original_records.parquet"),
        "benchmark_eligible": False,
        "production_eligible": False,
        "reasons": reasons,
        "files_in_archive": [f.filename for f in archive.infolist()],
        "source_notebook_executed": False,
    }
    (output / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/ml/richer")
    args = parser.parse_args()
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        mendeley = prepare_mendeley(client, args.output / MENDELEY_ID)
        print(
            json.dumps(
                {
                    "source": MENDELEY_ID,
                    "accepted_rows": mendeley["audit"]["accepted_rows"],
                    "positives": mendeley["positives"],
                    "production_blockers": mendeley["production_blockers"],
                }
            ),
            flush=True,
        )
        kaggle = audit_kaggle(client, args.output / KAGGLE_ID)
        print(
            json.dumps(
                {
                    "source": KAGGLE_ID,
                    "rows": kaggle["rows"],
                    "benchmark_eligible": False,
                    "reasons": kaggle["reasons"],
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
