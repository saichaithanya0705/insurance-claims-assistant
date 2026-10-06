"""Prepare reproducible educational Synapt corpora; this script never uploads anything."""

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

DATASET = "ziadatalabs/FreeInsuranceClaims100M"
SOURCE_URL = "https://huggingface.co/datasets/ziadatalabs/FreeInsuranceClaims100M"
ATTRIBUTION = "ZiadataLabs - FreeInsuranceClaims100M; CC BY-NC 4.0"
CLAIM_TYPES = ("auto", "business", "home", "property", "renters")
CARD_FIELDS = (
    "claim_id",
    "policy_id",
    "claim_type",
    "state",
    "policyholder_tenure_years",
    "previous_claims_count",
    "incident_date",
    "claim_filed_date",
    "claim_amount",
    "deductible",
    "claim_status",
    "days_to_resolution",
)
DISCLAIMER = (
    "Educational decision support only. This document does not decide coverage, approve or "
    "deny a claim, authorize payment, or establish fraud. A human claims handler must review "
    "evidence and applicable policy terms."
)
SOPS = (
    (
        "SOP-AUTO-001",
        "Synthetic auto documentation and theft procedure",
        (
            "For an auto claim, request an incident statement and repair estimate; for theft, "
            "request a police report when applicable. Confirm the document's relevance with the "
            "handler. Record which documents were supplied and which remain outstanding. A document "
            "name in an intake form records availability, not verified contents or authenticity. "
            "This is an illustrative training procedure, not an insurer rule or policy requirement."
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
            "or amount is unclear. This is an illustrative training procedure, not an insurer rule "
            "or policy requirement."
        ),
    ),
    (
        "SOP-BUSINESS-001",
        "Synthetic business loss documentation procedure",
        (
            "For business claims, request an incident statement and a loss assessment supported by "
            "loss documentation, such as an itemized asset list or the relevant accounting records. "
            "Separate submitted estimates from documented amounts. Ask the handler which evidence "
            "is applicable before requesting additional material. Business interruption coverage "
            "cannot be inferred from a business claim label. This is an illustrative training "
            "procedure, not an insurer rule or policy requirement."
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
            "historical claims is not itself contradictory evidence. This is an illustrative "
            "training procedure."
        ),
    ),
    (
        "SOP-REVIEW-001",
        "Synthetic coverage and human review boundary",
        (
            "Check the actual policy version, applicable wording and endorsements with the handler "
            "before assessing coverage. A historical approved or denied status does not explain the "
            "decision and does not bind a new claim. Numerical similarity is a comparison signal, "
            "not a probability of approval. A fraud-risk estimate is an investigation signal, not "
            "proof or an accusation. If policy terms or supporting evidence are unavailable, state "
            "the limitation and request handler review. Final decisions and external actions require "
            "human authorization. This is an illustrative training procedure, not legal advice."
        ),
    ),
)


def digest_json(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def numeric(value, minimum=0, maximum=1_000_000_000):
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and minimum <= value <= maximum
    )


def eligible_rows(source: Path, cutoff: date):
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise TypeError("Source must contain rows and provenance metadata")
    rows, metadata = payload["rows"], payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise TypeError("Source provenance metadata must be an object")
    digest = digest_json(rows)
    if metadata.get("rows_sha256") != digest:
        raise ValueError("Source rows SHA256 does not match provenance metadata")
    if (
        metadata.get("dataset") != DATASET
        or metadata.get("synthetic") is not True
        or metadata.get("license") != "CC-BY-NC-4.0"
    ):
        raise ValueError("Source must identify the attributed synthetic noncommercial dataset")
    excluded, eligible, seen = Counter(), [], set()
    source_fields = set()
    for row in rows:
        if not isinstance(row, dict):
            excluded["invalid_record"] += 1
            continue
        source_fields.update(row)
        if row.get("claim_status") not in ("approved", "denied"):
            excluded["not_closed_status"] += 1
            continue
        if row.get("days_to_resolution") is None:
            excluded["missing_resolution_duration"] += 1
            continue
        if not all(key in row for key in CARD_FIELDS):
            excluded["invalid_record"] += 1
            continue
        try:
            incident = date.fromisoformat(row["incident_date"])
            filed = date.fromisoformat(row["claim_filed_date"])
            if not numeric(row["days_to_resolution"], maximum=36500) or incident > filed:
                raise ValueError("Invalid historical dates or duration")
            # Match the existing prepare_synapt_pack and HistoricalRetriever date semantics:
            # date + timedelta uses its whole-day component; fractional days are not rounded.
            closed = filed + timedelta(days=row["days_to_resolution"])
            valid = (
                isinstance(row["claim_id"], str)
                and re.fullmatch(r"CLM-[A-Za-z0-9-]{1,100}", row["claim_id"])
                and isinstance(row["policy_id"], str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", row["policy_id"])
                and row["claim_type"] in CLAIM_TYPES
                and isinstance(row["state"], str)
                and re.fullmatch(r"[A-Z]{2}", row["state"])
                and numeric(row["claim_amount"])
                and numeric(row["deductible"])
                and numeric(row["policyholder_tenure_years"], maximum=100)
                and isinstance(row["previous_claims_count"], int)
                and not isinstance(row["previous_claims_count"], bool)
                and 0 <= row["previous_claims_count"] <= 1000
            )
            if not valid:
                raise ValueError("Invalid historical fields")
        except (ValueError, TypeError, OverflowError):
            excluded["invalid_record"] += 1
            continue
        if closed >= cutoff:
            excluded["closed_on_or_after_cutoff"] += 1
            continue
        if row["claim_id"] in seen:
            excluded["duplicate_claim_id"] += 1
            continue
        seen.add(row["claim_id"])
        eligible.append((row, closed))
    eligible.sort(key=lambda item: item[0]["claim_id"])
    summary = {
        "dataset": DATASET,
        "source_url": SOURCE_URL,
        "license": "CC-BY-NC-4.0",
        "attribution": ATTRIBUTION,
        "synthetic": True,
        "source_rows_sha256": digest,
        "source_file_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_row_count": len(rows),
        "eligible_count": len(eligible),
        "excluded_count": sum(excluded.values()),
        "excluded_reasons": dict(sorted(excluded.items())),
        "excluded_source_fields": sorted(source_fields - set(CARD_FIELDS)),
        "cutoff_exclusive": cutoff.isoformat(),
        "closure_derivation": "filing date + timedelta(days=duration); whole-day date semantics",
        "sampling": "Bounded local API slice; not representative of an insurer or population",
    }
    return eligible, summary


def choose_pilot(eligible, count):
    groups = defaultdict(list)
    for item in eligible:
        groups[item[0]["claim_type"]].append(item)
    if not groups or count < len(groups) or count > len(eligible):
        raise ValueError("Pilot count must cover available types and not exceed eligible records")
    selected = []
    position = 0
    while len(selected) < count:
        for kind in sorted(groups):
            if position < len(groups[kind]) and len(selected) < count:
                selected.append(groups[kind][position])
        position += 1
    return selected


def header(source_id, title, provenance, attribution):
    return (
        f"# {title}\nsource_id: {source_id}\nprovenance: {provenance}\n"
        f"attribution: {attribution}\n{DISCLAIMER}\n"
    )


def historical_card(row, closed):
    body = header(
        "history:" + row["claim_id"],
        "Synthetic historical claim " + row["claim_id"],
        "published_synthetic_dataset",
        ATTRIBUTION,
    )
    body += "source_url: " + SOURCE_URL + "\n"
    body += "This is an original tabular synthetic record, with no incident narrative supplied.\n"
    body += "\n".join(f"{key}: {row[key]}" for key in CARD_FIELDS) + "\n"
    body += (
        f"derived_closed_date: {closed.isoformat()}\n"
        "Closure date is derived from the recorded filing date and resolution duration.\n"
        "No coverage, denial reason, loss cause or fraud proof can be inferred from this record.\n"
    )
    return body


def sop_document(source_id, title, body):
    return (
        header(
            source_id,
            title,
            "hand_authored_synthetic_procedure",
            "Synapt Claims Investigator project - independently authored educational example",
        )
        + "\n"
        + body
        + "\n"
    )


def batches(cards, max_cards, max_bytes):
    result, current, current_bytes = [], [], 0
    for row, text in cards:
        size = len(text.encode("utf-8")) + (1 if current else 0)
        if len(text.encode("utf-8")) > max_bytes:
            raise ValueError("A single historical card exceeds the batch byte limit")
        if current and (len(current) >= max_cards or current_bytes + size > max_bytes):
            result.append(current)
            current, current_bytes, size = [], 0, len(text.encode("utf-8"))
        current.append((row, text))
        current_bytes += size
    if current:
        result.append(current)
    return result


def file_record(path, content, source_ids, claim_ids=None, *, uploadable=True):
    raw = content.encode("utf-8")
    return {
        "path": path,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "source_ids": source_ids,
        "claim_ids": claim_ids or [],
        "uploadable": uploadable,
    }


def make_corpus(eligible, summary, *, pilot, pilot_count, max_cards, max_bytes):
    selected = choose_pilot(eligible, pilot_count) if pilot else eligible
    if not selected:
        raise ValueError("No eligible historical records are available")
    cards = [(row, historical_card(row, closed)) for row, closed in selected]
    files, records = {}, []
    if pilot:
        for row, text in cards:
            path = f"upload/claim-{row['claim_id']}.txt"
            if len(text.encode("utf-8")) > 12 * 1024:
                raise ValueError("Pilot historical document exceeds 12 KiB")
            files[path] = text
            records.append(
                file_record(path, text, ["history:" + row["claim_id"]], [row["claim_id"]])
            )
        for source_id, title, body in SOPS:
            text = sop_document(source_id, title, body)
            path = f"upload/{source_id.lower()}.txt"
            if len(text.encode("utf-8")) > 12 * 1024:
                raise ValueError("Pilot procedure exceeds 12 KiB")
            files[path] = text
            records.append(file_record(path, text, [source_id]))
        combined = "\n".join(files.values())
        if len(combined.encode("utf-8")) > 25 * 1024:
            raise ValueError("Combined pilot exceeds 25 KiB")
        path = "pilot-combined.txt"
        files[path] = combined
        records.append(
            file_record(
                path,
                combined,
                [sid for item in records for sid in item["source_ids"]],
                [row["claim_id"] for row, _ in cards],
            )
        )
    else:
        for index, batch in enumerate(batches(cards, max_cards, max_bytes), start=1):
            text = "\n".join(text for _, text in batch)
            path = f"upload/claims-{index:04d}.txt"
            files[path] = text
            records.append(
                file_record(
                    path,
                    text,
                    ["history:" + r["claim_id"] for r, _ in batch],
                    [r["claim_id"] for r, _ in batch],
                )
            )
    probes = []
    for row, _ in cards:
        probes.append(
            {
                "source_id": "history:" + row["claim_id"],
                "claim_id": row["claim_id"],
                "source_row_sha256": digest_json(row),
                "expected_snippets": [
                    f"claim_id: {row['claim_id']}",
                    f"claim_type: {row['claim_type']}",
                    f"claim_amount: {row['claim_amount']}",
                    f"deductible: {row['deductible']}",
                ],
            }
        )
    qa = {
        "warning": "NOT FOR UPLOAD. Local QA queries and expectations; never ingest this file.",
        "historical_probes": [
            {
                "question": f"What recorded claim amount and deductible belong to {p['claim_id']}?",
                "required_source_id": p["source_id"],
                "expected_snippets": p["expected_snippets"],
            }
            for p in probes
        ],
        "procedure_probes": [
            {
                "required_source_id": source_id,
                "question": f"Retrieve the procedure titled '{title}'",
                "expected_snippet": body.split(". ", 1)[0] + ".",
            }
            for source_id, title, body in SOPS
        ]
        if pilot
        else [],
    }
    qa_content = json.dumps(qa, indent=2, ensure_ascii=False) + "\n"
    files["QA_NOT_FOR_UPLOAD.json"] = qa_content
    records.append(file_record("QA_NOT_FOR_UPLOAD.json", qa_content, [], uploadable=False))
    manifest = {
        "schema_version": 1,
        "kind": "pilot" if pilot else "expansion",
        "source": summary,
        "historical_cards": len(cards),
        "claim_ids": [row["claim_id"] for row, _ in cards],
        "claim_type_counts": dict(sorted(Counter(row["claim_type"] for row, _ in cards).items())),
        "synthetic_procedure_documents": len(SOPS) if pilot else 0,
        "upload_document_count": sum(item["path"].startswith("upload/") for item in records),
        "batch_max_cards": 1 if pilot else max_cards,
        "batch_max_bytes": 12 * 1024 if pilot else max_bytes,
        "files": records,
        "factual_probes": probes,
        "synapt_uploaded": False,
        "extraction_verified": False,
        "upload_instructions": "Upload only upload/ documents OR pilot-combined.txt, never both. "
        "Manifest and QA expectations are not for upload. Expansion is prepared only.",
    }
    files["manifest.json"] = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    return files, manifest


def validate_output_plan(output, files):
    existing = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}
    if existing - files.keys():
        raise ValueError(
            "Existing corpus contains unrecognized files; use a fresh version directory"
        )
    for relative, text in files.items():
        path = output / relative
        if path.exists() and (not path.is_file() or path.read_bytes() != text.encode("utf-8")):
            raise ValueError("Conflicting generated content exists; refusing to overwrite it")


def write_without_conflicts(output, files):
    validate_output_plan(output, files)
    # Check the complete plan before creating files to avoid partial changes on ordinary conflicts.
    for relative, text in files.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(text.encode("utf-8"))


def prepare(
    source,
    pilot_output,
    expansion_output,
    *,
    cutoff=date(2026, 1, 1),
    pilot_count=10,
    max_cards=100,
    max_bytes=60 * 1024,
):
    if not 1 <= max_cards <= 100 or not 1024 <= max_bytes <= 60 * 1024:
        raise ValueError("Batch limits must be 1..100 cards and 1024..61440 UTF-8 bytes")
    resolved_pilot, resolved_expansion = pilot_output.resolve(), expansion_output.resolve()
    if (
        resolved_pilot == resolved_expansion
        or resolved_pilot in resolved_expansion.parents
        or resolved_expansion in resolved_pilot.parents
    ):
        raise ValueError("Pilot and expansion must use separate, nonnested directories")
    eligible, summary = eligible_rows(source, cutoff)
    outputs = {}
    plans = []
    for name, destination, pilot in (
        ("pilot", pilot_output, True),
        ("expansion", expansion_output, False),
    ):
        files, manifest = make_corpus(
            eligible,
            summary,
            pilot=pilot,
            pilot_count=pilot_count,
            max_cards=max_cards,
            max_bytes=max_bytes,
        )
        plans.append((destination, files))
        outputs[name] = manifest
    for destination, files in plans:
        validate_output_plan(destination, files)
    for destination, files in plans:
        write_without_conflicts(destination, files)
    return outputs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/raw/claims_sample.json"))
    parser.add_argument("--pilot-output", type=Path, default=Path("artifacts/synapt/pilot-v1"))
    parser.add_argument(
        "--expansion-output", type=Path, default=Path("artifacts/synapt/expansion-v1")
    )
    parser.add_argument("--cutoff", type=date.fromisoformat, default=date(2026, 1, 1))
    args = parser.parse_args()
    manifests = prepare(args.source, args.pilot_output, args.expansion_output, cutoff=args.cutoff)
    print(
        json.dumps(
            {
                name: {
                    key: manifest[key]
                    for key in (
                        "historical_cards",
                        "claim_type_counts",
                        "upload_document_count",
                        "synthetic_procedure_documents",
                        "synapt_uploaded",
                    )
                }
                | {"source": manifest["source"]}
                for name, manifest in manifests.items()
            },
            indent=2,
        )
    )
