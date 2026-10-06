import re
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimType(StrEnum):
    AUTO = "auto"
    HOME = "home"
    RENTERS = "renters"
    PROPERTY = "property"
    BUSINESS = "business"


class ClaimInput(StrictModel):
    description: str = Field(min_length=10, max_length=6000)
    claim_type: ClaimType | None = None
    state: str = Field(pattern=r"^[A-Z]{2}$")
    incident_date: date
    claim_filed_date: date
    claim_amount: float = Field(ge=0, le=1_000_000_000, allow_inf_nan=False)
    deductible: float = Field(ge=0, le=1_000_000_000, allow_inf_nan=False)
    previous_claims_count: int = Field(ge=0, le=1000)
    policyholder_tenure_years: float = Field(ge=0, le=100, allow_inf_nan=False)
    provided_documents: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def check_dates(self):
        if self.claim_filed_date < self.incident_date:
            raise ValueError("Filing date must be on or after the incident date")
        if (
            self.incident_date > datetime.now(UTC).date()
            or self.claim_filed_date > datetime.now(UTC).date()
        ):
            raise ValueError("Incident and filing dates cannot be in the future")
        return self


class SearchFilters(StrictModel):
    claim_type: ClaimType | None = None
    state: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    claim_status: Literal["approved", "denied"] | None = None
    min_amount: float = Field(default=0, ge=0, allow_inf_nan=False)
    max_amount: float = Field(default=1_000_000_000, ge=0, allow_inf_nan=False)
    min_previous_claims: int = Field(default=0, ge=0)
    max_previous_claims: int = Field(default=1000, ge=0)

    @model_validator(mode="after")
    def check_ranges(self):
        if self.min_amount > self.max_amount:
            raise ValueError("Minimum amount exceeds maximum amount")
        if self.min_previous_claims > self.max_previous_claims:
            raise ValueError("Minimum claim history exceeds maximum claim history")
        return self


class Evidence(StrictModel):
    source_id: str
    title: str
    text: str
    provenance: Literal["synthetic_fixture", "published_synthetic", "synapt", "user_input"]
    provider_id: str | None = None


class RetrievalBundle(StrictModel):
    mode: Literal["fixture", "live"]
    evidence: list[Evidence]
    warnings: list[str] = Field(default_factory=list)


class Finding(StrictModel):
    kind: Literal["fact", "gap", "risk_indicator", "limitation", "contradiction"]
    text: str
    source_ids: list[str] = Field(
        default_factory=list,
        description="Supplied source IDs supporting this finding; nonempty for every kind except limitation.",
    )

    @model_validator(mode="after")
    def supported_finding(self):
        if self.kind != "limitation" and not self.source_ids:
            raise ValueError("Substantive findings require supporting source IDs")
        if self.kind == "contradiction" and re.match(
            r"^\s*no\s+(?:contradictions?|inconsistencies?)\b", self.text, re.IGNORECASE
        ):
            raise ValueError("Absence of a contradiction cannot be labeled a contradiction")
        return self


class ReviewDecision(StrictModel):
    decision: Literal["accept_brief", "request_revision"]
    note: str = Field(min_length=3, max_length=2000)
