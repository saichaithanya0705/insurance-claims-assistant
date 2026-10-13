"""Test double for Synapt. Never importable from the application (it lives under tests/)."""

from claims.core.schemas import ClaimInput, Evidence, RetrievalBundle


class StubSynaptAdapter:
    """Unit-test double for the Synapt boundary. It exists only under tests/: the product has no
    fixture mode, no fallback adapter and no setting that selects a stand-in for Synapt."""

    def retrieve(self, claim: ClaimInput) -> RetrievalBundle:
        docs = [
            (
                "fixture-procedure-auto",
                "Synthetic auto handling procedure",
                (
                    "For an auto claim, request an incident statement and repair estimate; "
                    "for theft, request a police report when applicable."
                ),
            ),
            (
                "fixture-procedure-property",
                "Synthetic property handling procedure",
                (
                    "For home, renters or property claims, request an incident statement, "
                    "damage photographs and a damage assessment (an itemized repair estimate). "
                    "For renters claims, request an inventory list of damaged or lost items. "
                    "For business claims, request an incident statement and a loss assessment "
                    "supported by loss documentation."
                ),
            ),
            (
                "fixture-review-boundary",
                "Synthetic review and coverage boundary",
                (
                    "Policy wording and applicable endorsements must be checked before a coverage "
                    "decision. Similar cases do not establish coverage or prove fraud. "
                    "A human claims handler reviews recommendations before any final decision."
                ),
            ),
        ]
        return RetrievalBundle(
            mode="fixture",
            evidence=[
                Evidence(source_id=key, title=title, text=text, provenance="synthetic_fixture")
                for key, title, text in docs
            ],
            warnings=["Synthetic procedure fixtures; live Synapt retrieval has not been verified."],
        )

    async def ingest(self, text: str, name: str) -> dict:
        return {"req_id": "local"}
