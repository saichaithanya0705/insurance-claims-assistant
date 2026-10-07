"""Validate intake snapshots against separately supplied human adjudication records."""

from collections import Counter
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from claims.richer_data import (
    ASSESSMENT_CATEGORICAL,
    BASE_CATEGORICAL,
    BASE_NUMERIC,
    INCIDENT_CATEGORICAL,
    INCIDENT_NUMERIC,
    binary_label,
    canonical_digest,
    optional_text,
)


class Adjudication(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    evidence_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    is_fraud: bool = Field(strict=True)
    observed_at: datetime
    adjudicator: str = Field(min_length=1)
    method: Literal["human_review", "final_adjudication"]
    evidence_reference: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_observation(self):
        if self.observed_at.tzinfo is None or self.observed_at > datetime.now(UTC):
            raise ValueError("Adjudication needs an explicit timezone and cannot be in the future")
        self.observed_at = self.observed_at.astimezone(UTC)
        return self


class ReviewedSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    claim_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    claim_type: Literal["auto", "home", "renters", "property", "business"]
    incident_date: date
    claim_filed_at: datetime
    features_observed_at: datetime
    label_observed_at: datetime
    label_evidence_id: str = Field(min_length=1)
    is_fraud: bool = Field(strict=True)

    @model_validator(mode="after")
    def ordered_observations(self):
        timestamps = (self.claim_filed_at, self.features_observed_at, self.label_observed_at)
        if any(t.tzinfo is None for t in timestamps):
            raise ValueError("All snapshot/label timestamps need explicit timezones")
        if (
            self.incident_date > self.claim_filed_at.date()
            or self.features_observed_at > self.claim_filed_at
            or self.label_observed_at < self.claim_filed_at
            or max(timestamps) > datetime.now(UTC)
        ):
            raise ValueError("Invalid incident, intake feature or outcome observation order")
        return self


def reviewed_records(raw_rows, evidence_rows, source_id):
    if not isinstance(evidence_rows, list):
        raise TypeError("Separate adjudication evidence must be a JSON array")
    evidence = {}
    for raw in evidence_rows:
        item = Adjudication.model_validate(raw)
        if item.evidence_id in evidence:
            raise ValueError("Duplicate adjudication evidence IDs")
        evidence[item.evidence_id] = item
    rows, rejected = [], []
    keys = set(ReviewedSnapshot.model_fields)
    numeric = set(BASE_NUMERIC + INCIDENT_NUMERIC) - {"incident_month"}
    categories = set(BASE_CATEGORICAL + INCIDENT_CATEGORICAL + ASSESSMENT_CATEGORICAL)
    # Catch accidental model/outcome fields, including risk scores and settlement values.
    allowed = keys | numeric | categories | {"currency"}
    seen_claims, seen_evidence = set(), set()
    for index, raw in enumerate(raw_rows, 1):
        try:
            if set(raw) - allowed:
                raise ValueError("Unexpected feature/outcome columns in reviewed CSV")
            snapshot = ReviewedSnapshot.model_validate(
                {
                    **{k: raw[k] for k in keys if k in raw},
                    "is_fraud": binary_label(
                        raw["is_fraud"], vocabulary={"true": True, "false": False}
                    ),
                }
            )
            item = evidence.get(snapshot.label_evidence_id)
            if (
                item is None
                or item.claim_id != snapshot.claim_id
                or item.is_fraud != snapshot.is_fraud
                or item.observed_at != snapshot.label_observed_at
            ):
                raise ValueError("Label differs from separate adjudication evidence")
            if snapshot.claim_id in seen_claims or snapshot.label_evidence_id in seen_evidence:
                raise ValueError("Duplicate claim or reused adjudication evidence")
            row = {
                "claim_id": f"{source_id}:{snapshot.claim_id}",
                "policy_id": f"{source_id}:{snapshot.policy_id}",
                "source_id": source_id,
                "source_row": index,
                "raw_row_sha256": canonical_digest(raw),
                "claim_type": snapshot.claim_type,
                "currency": optional_text(raw.get("currency", "")),
                "incident_date": snapshot.incident_date.isoformat(),
                "claim_filed_date": snapshot.claim_filed_at.date().isoformat(),
                "claim_filed_at": snapshot.claim_filed_at.astimezone(UTC).isoformat(),
                "features_observed_at": snapshot.features_observed_at.astimezone(UTC).isoformat(),
                "label_observed_at": snapshot.label_observed_at.astimezone(UTC).isoformat(),
                "label_evidence_id": snapshot.label_evidence_id,
                "is_fraud": snapshot.is_fraud,
                "original_label": raw["is_fraud"],
                "incident_month": snapshot.incident_date.month,
            }
            for key in numeric:
                text = optional_text(raw.get(key, ""))
                value = float(text) if text is not None else None
                if value is not None and (not -float("inf") < value < float("inf") or value < 0):
                    raise ValueError("Invalid reviewed numeric feature")
                limits = {
                    "tenure_years": 100,
                    "vehicles_involved": 100,
                    "bodily_injuries": 100,
                    "witnesses": 1000,
                    "vehicle_age_years": 100,
                    "incident_hour": 23,
                }
                count_keys = {
                    "vehicles_involved",
                    "bodily_injuries",
                    "witnesses",
                    "vehicle_age_years",
                    "incident_hour",
                }
                if value is not None and (
                    value > limits.get(key, 1_000_000_000)
                    or (key in count_keys and value != int(value))
                ):
                    raise ValueError("Reviewed counts, hours or feature ranges are invalid")
                row[key] = value
            row.update({key: optional_text(raw.get(key, "")) for key in categories})
            if any(row.get(key) is None for key in ("claim_amount", "deductible", "tenure_years")):
                raise ValueError("Missing core reviewed features")
            rows.append(row)
            seen_claims.add(snapshot.claim_id)
            seen_evidence.add(snapshot.label_evidence_id)
        except (ValueError, KeyError, TypeError) as error:
            rejected.append(
                {"source_row": index, "reason": str(error), "raw_row_sha256": canonical_digest(raw)}
            )
    # A duplicate/conflicting identity invalidates every version, even the earlier accepted row.
    claim_counts = Counter(str(r.get("claim_id", "")).strip() for r in raw_rows)
    conflict_ids = {key for key, count in claim_counts.items() if count > 1}
    clean = [r for r in rows if r["claim_id"].removeprefix(source_id + ":") not in conflict_ids]
    clean_ids = {r["claim_id"] for r in clean}
    for row in rows:
        if row["claim_id"] not in clean_ids:
            rejected.append(
                {
                    "source_row": row["source_row"],
                    "reason": "conflicting_claim",
                    "raw_row_sha256": row["raw_row_sha256"],
                }
            )
    return sorted(clean, key=lambda r: (r["claim_filed_date"], r["claim_id"])), {
        "input_rows": len(raw_rows),
        "accepted_rows": len(clean),
        "rejected_rows": len(rejected),
        "rejections": rejected,
        "adjudication_records": len(evidence),
        "evidence_cross_checks": len(clean),
        "verification_scope": "Cross-checked supplied human evidence; authenticity requires source review",
    }
