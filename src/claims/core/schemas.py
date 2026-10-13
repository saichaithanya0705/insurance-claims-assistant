import re
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Same list the interface offers: the 50 states and the District of Columbia.
US_STATE_CODES = frozenset(
    {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN",
        "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
        "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
        "VT", "VA", "WA", "WV", "WI", "WY",
    }
)  # fmt: skip

_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_PHONE = re.compile(r"(?<![\d-])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?![\d-])")
# Contiguous 13-19 digits, or the usual 4-4-4-x and 4-6-5 groupings; never loose digit runs, so
# adjacent dates such as "2026-09-04 2026-09-06" are not mistaken for a card.
_CARD = re.compile(
    r"(?<![\d-])(?:\d{13,19}|\d{4}([ -])\d{4}\1\d{4}\1\d{1,7}|\d{4}([ -])\d{6}\2\d{4,5})(?![\d-])"
)


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def redact_personal_data(text: str) -> str:
    """Mask identifiers a handler never needs (SSN, payment card, email, phone).

    Applied when a claim is accepted, so the masked text is what gets stored, sent to a language
    model and used in any retrieval query. Cards are masked only when they pass the Luhn check,
    which keeps ordinary long numbers (amounts, policy numbers) intact."""
    text = _SSN.sub("[SSN REDACTED]", text)
    text = _EMAIL.sub("[EMAIL REDACTED]", text)
    text = _CARD.sub(
        lambda m: "[CARD REDACTED]"
        if _luhn_valid(re.sub(r"\D", "", m.group()))
        else m.group(),
        text,
    )
    return _PHONE.sub("[PHONE REDACTED]", text)


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

    @field_validator("description")
    @classmethod
    def meaningful_description(cls, value):
        text = value.strip()
        # Blank, digit-only or symbol-only text is not an incident description and would only
        # start a full investigation on nothing.
        if len(text) < 10 or sum(ch.isalpha() for ch in text) < 5:
            raise ValueError("Describe the incident in words: at least 10 characters with letters")
        return redact_personal_data(text)

    @field_validator("state")
    @classmethod
    def real_state(cls, value):
        if value not in US_STATE_CODES:
            raise ValueError("State must be a US state or DC code, for example TX")
        return value

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
    claim_status: Literal["approved", "denied", "pending", "under_review"] | None = None
    min_amount: float = Field(default=0, ge=0, allow_inf_nan=False)
    max_amount: float = Field(default=1_000_000_000, ge=0, allow_inf_nan=False)
    min_previous_claims: int = Field(default=0, ge=0)
    max_previous_claims: int = Field(default=1000, ge=0)

    @field_validator("state")
    @classmethod
    def real_state(cls, value):
        if value is not None and value not in US_STATE_CODES:
            raise ValueError("State must be a US state or DC code, for example TX")
        return value

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
    provenance: Literal[
        "synthetic_fixture",
        "published_synthetic",
        "synapt",
        "local_copy",
        "user_input",
        "handler_lesson",
    ]
    provider_id: str | None = None


class RetrievalBundle(StrictModel):
    mode: Literal["fixture", "live", "degraded"]
    evidence: list[Evidence]
    warnings: list[str] = Field(default_factory=list)
    # Claim IDs of historical cards Synapt judged semantically similar, best match first.
    semantic_claim_ids: list[str] = Field(default_factory=list)


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
