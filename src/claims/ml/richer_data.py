"""Source-preserving import of richer claim records for isolated ML experiments."""

import csv
import hashlib
import io
import json
import math
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from claims.ml.fraud_features import file_digest, rows_digest

MENDELEY_ID = "mendeley_992mh7dk9y_v2"
KAGGLE_ID = "kaggle_claims_2026_v1"
BASE_NUMERIC = ("claim_amount", "deductible", "tenure_years", "incident_month")
BASE_CATEGORICAL = ("policy_state",)
INCIDENT_NUMERIC = (
    "vehicles_involved",
    "bodily_injuries",
    "witnesses",
    "vehicle_age_years",
    "incident_hour",
)
INCIDENT_CATEGORICAL = (
    "incident_type",
    "collision_type",
    "incident_state",
    "vehicle_make",
    "vehicle_model",
)
# Availability of these assessment/document fields at intake must be verified separately.
ASSESSMENT_CATEGORICAL = (
    "incident_severity",
    "police_report_available",
    "property_damage",
    "authorities_contacted",
)
MISSING = {"", "?", "nan", "null", "none", "n/a"}
EXPECTED_MENDELEY_COLUMNS = {
    "policy_number",
    "incident_date",
    "fraud_reported",
    "months_as_customer",
    "policy_state",
    "policy_deductable",
    "total_claim_amount",
    "incident_type",
    "collision_type",
    "incident_state",
    "incident_severity",
    "police_report_available",
    "property_damage",
    "authorities_contacted",
    "number_of_vehicles_involved",
    "bodily_injuries",
    "witnesses",
    "auto_make",
    "auto_model",
    "auto_year",
    "incident_hour_of_the_day",
}


def canonical_digest(row):
    return hashlib.sha256(
        json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def parse_csv(data):
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
    names = reader.fieldnames or []
    if not names or len(names) != len(set(names)):
        raise ValueError("CSV must have unique named columns")
    rows = list(reader)
    if not rows or any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("CSV must contain complete, consistently shaped records")
    return names, rows


def optional_text(value):
    value = str(value).strip()
    return None if value.lower() in MISSING else value


def number(row, key, *, maximum=1_000_000_000, integer=False):
    value = optional_text(row[key])
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= maximum or (integer and value != int(value)):
        raise ValueError(f"Invalid {key}")
    return int(value) if integer else value


def binary_label(value, *, vocabulary):
    if value not in vocabulary:
        raise ValueError("Missing or invalid original binary fraud label")
    return vocabulary[value]


def normalize_mendeley(raw, row_number):
    incident = date.fromisoformat(raw["incident_date"])
    if incident > datetime.now(UTC).date():
        raise ValueError("Future incident date")
    policy = optional_text(raw["policy_number"])
    if not policy:
        raise ValueError("Missing policy identifier")
    label = binary_label(raw["fraud_reported"], vocabulary={"Y": True, "N": False})
    vehicle_year = number(raw, "auto_year", maximum=incident.year, integer=True)
    key = hashlib.sha256(f"{policy}|{incident.isoformat()}".encode()).hexdigest()[:24]
    normalized = {
        "claim_id": f"{MENDELEY_ID}:{key}",
        "policy_id": f"{MENDELEY_ID}:{policy}",
        "source_id": MENDELEY_ID,
        "source_row": row_number,
        "raw_row_sha256": canonical_digest(raw),
        "claim_type": "auto",
        "currency": None,
        "incident_date": incident.isoformat(),
        "claim_filed_date": None,
        "features_observed_at": None,
        "label_observed_at": None,
        "label_evidence_id": None,
        "is_fraud": label,
        "original_label": raw["fraud_reported"],
        "claim_amount": number(raw, "total_claim_amount"),
        "deductible": number(raw, "policy_deductable"),
        "tenure_years": (
            number(raw, "months_as_customer", maximum=1200) / 12
            if optional_text(raw["months_as_customer"]) is not None
            else None
        ),
        "incident_month": incident.month,
        "vehicles_involved": number(raw, "number_of_vehicles_involved", maximum=100, integer=True),
        "bodily_injuries": number(raw, "bodily_injuries", maximum=100, integer=True),
        "witnesses": number(raw, "witnesses", maximum=100, integer=True),
        "vehicle_age_years": incident.year - vehicle_year if vehicle_year is not None else None,
        "incident_hour": number(raw, "incident_hour_of_the_day", maximum=23, integer=True),
    }
    mapping = {
        "policy_state": "policy_state",
        "incident_type": "incident_type",
        "collision_type": "collision_type",
        "incident_state": "incident_state",
        "vehicle_make": "auto_make",
        "vehicle_model": "auto_model",
        **{key: key for key in ASSESSMENT_CATEGORICAL},
    }
    normalized.update({key: optional_text(raw[column]) for key, column in mapping.items()})
    if any(normalized[key] is None for key in ("claim_amount", "deductible", "tenure_years")):
        raise ValueError("Missing core source feature")
    return normalized


def normalize_records(raw_rows):
    """Collapse exact repeats; quarantine *all* conflicting versions of a claim."""
    accepted = {}
    conflicts = set()
    rejected = []
    duplicates = 0
    for index, raw in enumerate(raw_rows, 1):
        try:
            row = normalize_mendeley(raw, index)
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            rejected.append(
                {"source_row": index, "reason": str(error), "raw_row_sha256": canonical_digest(raw)}
            )
            continue
        key = row["claim_id"]
        if key in conflicts:
            rejected.append(
                {
                    "source_row": index,
                    "reason": "conflicting_claim",
                    "raw_row_sha256": row["raw_row_sha256"],
                }
            )
        elif key in accepted:
            first = accepted[key]
            if first["raw_row_sha256"] == row["raw_row_sha256"]:
                duplicates += 1
            else:
                conflicts.add(key)
                accepted.pop(key)
                rejected.extend(
                    {
                        "source_row": r["source_row"],
                        "reason": "conflicting_claim",
                        "raw_row_sha256": r["raw_row_sha256"],
                    }
                    for r in (first, row)
                )
        else:
            accepted[key] = row
    return sorted(accepted.values(), key=lambda r: (r["incident_date"], r["claim_id"])), {
        "input_rows": len(raw_rows),
        "accepted_rows": len(accepted),
        "exact_duplicates_removed": duplicates,
        "conflicting_claims": len(conflicts),
        "rejected_rows": len(rejected),
        "rejections": rejected,
    }


def write_parquet(rows, path):
    """Write typed ZSTD Parquet atomically; an empty accepted dataset is an error."""
    if not rows:
        raise ValueError("Cannot export an empty dataset")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    json_path = path.with_suffix(".jsonl.tmp")
    parquet_path = path.with_suffix(".parquet.tmp")
    # Preserve timestamp strings exactly; DuckDB's JSON auto-detection can otherwise
    # discard their timezone and change a canonical record during the round trip.
    schema = {}
    for key in rows[0]:
        values = [r[key] for r in rows if r[key] is not None]
        if values and all(type(v) is bool for v in values):
            schema[key] = "BOOLEAN"
        elif values and all(type(v) is int for v in values):
            schema[key] = "BIGINT"
        elif values and all(type(v) in (int, float) for v in values):
            schema[key] = "DOUBLE"
        else:
            schema[key] = "VARCHAR"
    try:
        with json_path.open("w", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, allow_nan=False) + "\n")
        with duckdb.connect() as connection:
            connection.execute("SET threads=1")
            connection.execute("SET memory_limit='512MB'")
            connection.read_json(
                str(json_path), format="newline_delimited", columns=schema
            ).write_parquet(str(parquet_path), compression="zstd")
        parquet_path.replace(path)
    finally:
        json_path.unlink(missing_ok=True)
        parquet_path.unlink(missing_ok=True)


def read_parquet(path):
    with duckdb.connect() as connection:
        cursor = connection.execute("SELECT * FROM read_parquet(?)", [str(path)])
        names = [field[0] for field in cursor.description]
        rows = [dict(zip(names, row)) for row in cursor.fetchall()]
    for row in rows:
        for key, value in row.items():
            if isinstance(value, date):
                row[key] = value.isoformat()
    return rows


def verified_records(manifest_path):
    """Rebuild canonical records from immutable raw CSV, never trust stored labels."""
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reviewed = manifest.get("adapter") == "reviewed_v1"
    if (manifest.get("source_id") != MENDELEY_ID and not reviewed) or not manifest.get(
        "benchmark_eligible"
    ):
        raise ValueError("Source is not eligible for the richer-claims experiment")
    raw_path = manifest_path.parent / manifest["raw_csv"]
    parquet_path = manifest_path.parent / manifest["parquet"]
    for path, digest in (
        (raw_path, manifest["raw_csv_sha256"]),
        (parquet_path, manifest["parquet_sha256"]),
    ):
        if file_digest(path) != digest:
            raise ValueError("Dataset file differs from its frozen source manifest")
    columns, raw_rows = parse_csv(raw_path.read_bytes())
    if reviewed:
        from claims.ml.reviewed_claims import reviewed_records

        evidence_path = manifest_path.parent / manifest["evidence"]
        if file_digest(evidence_path) != manifest["evidence_sha256"]:
            raise ValueError("Separate adjudication evidence changed")
        rows, audit = reviewed_records(
            raw_rows, json.loads(evidence_path.read_text(encoding="utf-8")), manifest["source_id"]
        )
    else:
        if not EXPECTED_MENDELEY_COLUMNS <= set(columns):
            raise ValueError("Original source schema changed")
        rows, audit = normalize_records(raw_rows)
    stored = read_parquet(parquet_path)
    if len(stored) != len({r["claim_id"] for r in stored}):
        raise ValueError("Stored richer dataset has duplicate IDs")
    if rows_digest(rows) != rows_digest(stored) or rows_digest(rows) != manifest["rows_sha256"]:
        raise ValueError("Parquet features or labels differ from original source")
    if audit["accepted_rows"] != manifest["audit"]["accepted_rows"]:
        raise ValueError("Source acceptance counts changed")
    return manifest, rows


def production_blockers(manifest, rows):
    blockers = []
    if manifest.get("label_verification") != "independently_adjudicated":
        blockers.append(
            "Fraud labels preserved from publisher; independent adjudication unverified"
        )
    if manifest.get("feature_availability") != "verified_at_intake":
        blockers.append("Intake-time availability of source features is unverified")
    if manifest.get("domain") != "us_property_and_casualty":
        blockers.append("Source domain does not cover the active model's full claim-type contract")
    for key in (
        "claim_filed_date",
        "features_observed_at",
        "label_observed_at",
        "label_evidence_id",
    ):
        if any(not r.get(key) for r in rows):
            blockers.append(f"Original records lack {key}")
    return blockers
