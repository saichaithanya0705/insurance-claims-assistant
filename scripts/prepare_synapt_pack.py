"""Generate explicit synthetic historical cards for ingestion, with no invented narratives."""

import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path


def prepare(source, output, cutoff, limit=10, offset=0):
    if not 1 <= limit <= 5000 or offset < 0:
        raise ValueError("Limit must be 1..5000 and offset must be nonnegative")
    content = json.loads(source.read_text())
    digest = hashlib.sha256(
        json.dumps(content["rows"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if content["metadata"].get("rows_sha256") != digest:
        raise ValueError("Source rows SHA256 does not match provenance metadata")
    docs = [
        "# Synthetic claims demo pack",
        "Source: ZiadataLabs FreeInsuranceClaims100M, CC BY-NC 4.0; educational use only.",
        "These are tabular synthetic records. No incident narrative or policy coverage has been supplied.",
    ]
    count = 0
    eligible = 0
    for row in content["rows"]:
        if row["claim_status"] not in ("approved", "denied") or row["days_to_resolution"] is None:
            continue
        closed = date.fromisoformat(row["claim_filed_date"]) + timedelta(
            days=row["days_to_resolution"]
        )
        if closed >= cutoff:
            continue
        eligible += 1
        if eligible <= offset:
            continue
        if count >= limit:
            break
        count += 1
        docs.append("\n## Claim " + row["claim_id"])
        for key, value in row.items():
            if key != "is_fraud_flagged_ground_truth":
                docs.append(f"{key}: {value}")
        docs.append(
            f"derived_closed_date: {closed.isoformat()}; computed from filing date and duration"
        )
        docs.append(
            "No coverage, claim-denial reason, loss cause or fraud proof can be inferred from this record."
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(docs), encoding="utf-8")
    return {
        "cards": count,
        "offset": offset,
        "limit": limit,
        "source_rows_sha256": digest,
        "cutoff": cutoff.isoformat(),
        "path": str(output),
        "synapt_uploaded": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/raw/claims_sample.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/synapt/claims.md"))
    parser.add_argument("--cutoff", type=date.fromisoformat, default=date(2026, 1, 1))
    parser.add_argument(
        "--limit", type=int, default=10, help="First live pilot defaults to ten cards"
    )
    parser.add_argument(
        "--offset", type=int, default=0, help="Offset among temporally eligible cards"
    )
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(args.source, args.output, args.cutoff, args.limit, args.offset), indent=2
        )
    )
