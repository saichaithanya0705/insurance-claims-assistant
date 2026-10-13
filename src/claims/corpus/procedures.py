"""Additional handling procedures for the Synapt knowledge base (illustrative, hand-authored, synthetic).

The first five procedures (`claims.corpus.builder.SOPS`) are short paragraphs. Synapt extracts a graph from what it ingests, so these
twelve are written as ordered steps, each with a prerequisite and a responsible role, a stated applicability and a boundary,
which is the shape its Procedure, Step and Entity nodes hold. Five are specific to a claim type or to theft, four apply only
when a fact about the claim is true (the thresholds are the ones this application already uses to prioritise attention, not
insurer rules), one concerns the application's fraud review signal (worked out after retrieval, so no graph search selects it
yet), and two apply to every claim.

Nothing here invents an insurer rule, a legal deadline or policy wording: each document says it is an illustrative training
procedure, never decides a claim, and leaves every decision to a human claims handler. ``scripts/build_procedures.py`` writes
them to a folder in the same layout the uploader reads; nothing in this module uploads anything.
"""

import hashlib
import json
from pathlib import Path

from claims.corpus.builder import DISCLAIMER

ROLE_STAFF = "Claims support or intake staff"
ROLE_COORD = "Claims support or intake staff in coordination with the claims handler"
ROLE_HANDLER = "Human claims handler"

# (source_id, title, applies when, steps [(action, prerequisite, responsible)], boundary)
PROCEDURES: tuple[tuple[str, str, str, tuple[tuple[str, str, str], ...], str], ...] = (
    (
        "SOP-COLLISION-001",
        "Synthetic auto collision documentation procedure",
        "an auto claim reports a collision or other damage to the insured vehicle and no theft is reported",
        (
            ("Request the incident statement from the claimant.", "The claim has been identified as an auto claim and no theft is reported.", ROLE_STAFF),
            ("Request photographs of the damage and the repair estimate.", "The incident statement has been requested.", ROLE_STAFF),
            ("Record the other parties and vehicles named in the statement and any injury it reports.", "The incident statement has been received.", ROLE_STAFF),
            ("Ask the claims handler whether a police report or third-party details apply, for example when another vehicle or an injury is involved.", "The statement names another party or an injury.", ROLE_COORD),
            ("Compare the dates, place and damage described in the statement, the photographs and the estimate, and preserve any difference for the handler.", "The statement, photographs and estimate have been received.", ROLE_STAFF),
        ),
        "This procedure does not assess fault or liability and does not decide coverage.",
    ),
    (
        "SOP-THEFT-001",
        "Synthetic vehicle theft verification procedure",
        "an auto claim reports that the vehicle was stolen",
        (
            ("Request the police report reference and ask the claims handler whether the report applies.", "A theft has been reported on the claim.", ROLE_COORD),
            ("Request the incident statement covering when and where the vehicle was last seen and how it was secured.", "A theft has been reported on the claim.", ROLE_STAFF),
            ("Ask how many keys or key fobs exist and whether any were lost earlier.", "The incident statement has been requested.", ROLE_STAFF),
            ("Record whether the vehicle has been recovered and on what date.", "The incident statement has been received.", ROLE_STAFF),
            ("Compare the dates in the police report reference and the statement and preserve any difference for the handler.", "Both the report reference and the statement have been received.", ROLE_STAFF),
        ),
        "A theft report is not proof either way. This procedure does not accuse the claimant and does not decide coverage.",
    ),
    (
        "SOP-WATER-001",
        "Synthetic home water damage documentation procedure",
        "a home or property claim reports water damage, such as a burst pipe or a leak",
        (
            ("Request the incident statement describing the source of the water and when it was found.", "A home or property water claim has been identified.", ROLE_STAFF),
            ("Request photographs of the damage, taken before cleanup or repair where possible.", "The incident statement has been requested.", ROLE_STAFF),
            ("Request the plumber's or contractor's report on the cause.", "The incident statement has been received.", ROLE_STAFF),
            ("Request invoices for emergency mitigation, such as water removal and drying, and the repair estimate.", "The cause has been documented or requested.", ROLE_STAFF),
            ("Ask the claims handler whether maintenance history or earlier leaks matter here, and ask a neutral clarifying question if two descriptions of the cause differ.", "The statement and the contractor's report have been received.", ROLE_COORD),
        ),
        "Cause and coverage are for the claims handler to determine. No inference about maintenance or neglect is drawn from a missing document.",
    ),
    (
        "SOP-INVENTORY-001",
        "Synthetic renters belongings inventory procedure",
        "a renters claim reports damaged, lost or stolen belongings",
        (
            ("Request an itemized inventory with a description, quantity and approximate age of each item.", "A renters claim has been identified.", ROLE_STAFF),
            ("Request proof of ownership where available, such as receipts, photographs or serial numbers.", "The inventory has been received.", ROLE_STAFF),
            ("Mark each item as documented or as stated by the claimant only, and keep the two values apart.", "The inventory and any proof of ownership have been received.", ROLE_STAFF),
            ("Ask the claims handler which items are in scope and ask a focused question about any unclear item.", "The items have been marked.", ROLE_COORD),
            ("If theft is reported, request the police report reference.", "A theft is reported on the claim.", ROLE_STAFF),
        ),
        "A missing receipt does not make an item invalid. Valuation belongs to the claims handler.",
    ),
    (
        "SOP-DOWNTIME-001",
        "Synthetic business loss and downtime evidence procedure",
        "a business claim reports lost income, lost stock or a period when operations stopped",
        (
            ("Request the incident statement with the dates operations stopped and resumed.", "A business claim has been identified.", ROLE_STAFF),
            ("Request sales or revenue and payroll records for a comparison period to establish a baseline.", "The incident statement has been received.", ROLE_STAFF),
            ("Request an itemized stock or asset list with supporting invoices.", "The incident statement has been received.", ROLE_STAFF),
            ("Record the steps taken to limit the loss, such as temporary premises or reduced operations.", "The incident statement has been received.", ROLE_STAFF),
            ("Separate submitted estimates from documented amounts and mark each.", "The records and lists have been received.", ROLE_STAFF),
        ),
        "Business interruption coverage cannot be inferred from a business claim label. The claims handler decides what applies.",
    ),
    (
        "SOP-LATE-FILING-001",
        "Synthetic late-filed claim review procedure",
        "a claim is filed more than 30 days after the incident (the illustrative threshold this application uses to flag late reporting)",
        (
            ("Record the incident date and the filing date from the documents, not only from the intake form.", "The claim was filed more than 30 days after the incident.", ROLE_STAFF),
            ("Ask the claimant a neutral question about the reason for the delay.", "The dates have been recorded.", ROLE_COORD),
            ("Request any document dated near the incident that supports the timeline, such as a statement, photographs or a report.", "The reason for the delay has been given or requested.", ROLE_STAFF),
            ("Preserve any difference between the stated timeline and the documents for the claims handler.", "The supporting documents have been received.", ROLE_STAFF),
            ("Hand the explanation and the documents to the claims handler.", "The timeline has been compared.", ROLE_STAFF),
        ),
        "A late filing is a reason to ask a question. It is not evidence of wrongdoing and is not a reason to decline a claim on its own.",
    ),
    (
        "SOP-LARGE-LOSS-001",
        "Synthetic large loss escalation procedure",
        "the claimed amount is $50,000 or more (the illustrative threshold this application uses for a large loss)",
        (
            ("Flag the claim to a supervising claims handler so that it is visible.", "The claimed amount is $50,000 or more.", ROLE_STAFF),
            ("Request itemized support for the amount claimed, such as estimates, invoices or assessments.", "The claim has been flagged.", ROLE_STAFF),
            ("Ask the claims handler whether an independent estimate or inspection applies.", "The itemized support has been requested.", ROLE_COORD),
            ("Confirm the policy limits and the deductible against the actual policy with the claims handler.", "The itemized support has been received.", ROLE_COORD),
            ("Record who reviewed the claim and when.", "The review steps above are complete.", ROLE_STAFF),
        ),
        "The amount alone does not indicate a problem. This procedure decides nothing about coverage or payment.",
    ),
    (
        "SOP-REPEAT-CLAIMANT-001",
        "Synthetic repeat claimant history review procedure",
        "the policyholder has three or more earlier claims (the illustrative threshold this application uses for a frequent claimant history)",
        (
            ("List the earlier claims recorded on the policy with their dates, types and outcomes.", "The policyholder has three or more earlier claims.", ROLE_STAFF),
            ("Check whether any earlier claim is still open or concerns the same item, vehicle or property.", "The earlier claims have been listed.", ROLE_STAFF),
            ("Request details if the same loss appears to have been claimed before.", "An earlier claim appears to concern the same item.", ROLE_COORD),
            ("Preserve the findings with their source references.", "The earlier claims have been checked.", ROLE_STAFF),
            ("Hand the findings to the claims handler.", "The findings have been recorded.", ROLE_STAFF),
        ),
        "A number of earlier claims is not evidence of fraud. No conclusion is drawn from the count.",
    ),
    (
        "SOP-NEW-POLICY-001",
        "Synthetic new policyholder verification procedure",
        "the policy has been in force for less than a year",
        (
            ("Confirm the policy start date from the policy record with the claims handler and compare it with the incident date.", "The policy has been in force for less than a year.", ROLE_COORD),
            ("Ask the claims handler whether the loss falls within any waiting period or before the policy started, and do not assume either.", "The start date has been confirmed.", ROLE_COORD),
            ("Request documents showing ownership or occupancy at the policy start date where they apply.", "The loss is close to the policy start date.", ROLE_STAFF),
            ("Ask the claims handler to compare the application details with the claim details if they differ.", "Both sets of details are available.", ROLE_COORD),
        ),
        "A new policy is not itself a concern. This procedure decides nothing about coverage.",
    ),
    (
        "SOP-FRAUD-SIGNAL-001",
        "Synthetic fraud-flag review signal procedure",
        "this application's fraud review signal is above its review threshold",
        (
            ("Record the signal as a statistical indicator of the dataset's synthetic fraud flag, not as evidence about this claim.", "The review signal is above the review threshold.", ROLE_STAFF),
            ("Re-check the documents and dates for gaps and contradictions using the other procedures.", "The signal has been recorded.", ROLE_STAFF),
            ("Do not tell the claimant that fraud is suspected.", "The signal has been recorded.", ROLE_STAFF),
            ("Ask the claims handler whether a referral to a specialist review team applies under the actual process.", "The documents have been re-checked.", ROLE_COORD),
            ("Record the reasons for whatever the claims handler decides.", "The claims handler has decided.", ROLE_HANDLER),
        ),
        "The signal never justifies a denial and is not proof or an accusation.",
    ),
    (
        "SOP-OUTSTANDING-001",
        "Synthetic missing document follow-up procedure",
        "documents that were requested for a claim are still outstanding",
        (
            ("List the outstanding documents with the date each was requested.", "A document request is open.", ROLE_STAFF),
            ("Send a neutral reminder in plain language that names exactly what is missing and why it is needed; seven days after the request is the illustrative interval.", "The list has been made.", ROLE_STAFF),
            ("Ask the claims handler whether an alternative document can stand in when the original is not available.", "The claimant says a document is unavailable.", ROLE_COORD),
            ("Record each document as it arrives, with its date.", "A document has been received.", ROLE_STAFF),
            ("If documents are still outstanding after the reminders, tell the claims handler and let them decide the next step.", "The reminders have been sent.", ROLE_STAFF),
        ),
        "Missing documents do not by themselves make a claim invalid. Closing or pausing a claim belongs to the claims handler.",
    ),
    (
        "SOP-PRIVACY-001",
        "Synthetic personal data handling procedure",
        "any claim information is shared, copied into a note or sent to another system",
        (
            ("Mask identifiers such as Social Security numbers, payment card numbers, email addresses and phone numbers before sharing.", "Claim information is about to be shared.", ROLE_STAFF),
            ("Share only the fields the recipient needs.", "Claim information is about to be shared.", ROLE_STAFF),
            ("Do not paste personal details into questions asked of an external tool.", "A question is being written.", ROLE_STAFF),
            ("Refer to a claim by its identifier or alias rather than by a person's name.", "A note or message is being written.", ROLE_STAFF),
            ("Tell the claims handler about any accidental disclosure.", "An identifier was shared by mistake.", ROLE_STAFF),
        ),
        "This is an illustrative handling practice, not legal advice.",
    ),
)


def render(source_id: str, title: str, applies_when: str, steps, boundary: str) -> str:
    """One procedure as a document in the project's SOP layout, with its steps numbered and each prerequisite and role stated."""
    lines = [
        f"# {title}",
        f"source_id: {source_id}",
        "provenance: hand_authored_synthetic_procedure",
        "attribution: Synapt Claims Investigator project - illustrative educational example",
        DISCLAIMER,
        "",
        f"{title}. This procedure applies when {applies_when}.",
        "",
    ]
    for number, (action, prerequisite, responsible) in enumerate(steps, start=1):
        lines.append(f"Step {number}. {action} Prerequisite: {prerequisite} Responsible: {responsible}.")
    lines += ["", f"Boundary: {boundary} This is an illustrative training procedure, not an insurer rule, legal requirement or policy wording.", ""]
    return "\n".join(lines)


def build(output: Path) -> dict:
    """Write the procedures and a manifest the uploader reads; refuse to overwrite different content."""
    files = {f"procedures/{p[0].lower()}.txt": render(*p) for p in PROCEDURES}
    manifest = {
        "schema_version": 2,
        "note": "Additional illustrative handling procedures. Upload with: python scripts/synapt_ingest.py ingest --procedures-only --force --corpus <this folder>",
        "cards": 0,
        "batches": [],
        "procedures": sorted(files),
        "sha256": {name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name, text in files.items()},
        "source_ids": [p[0] for p in PROCEDURES],
    }
    files["manifest.json"] = json.dumps(manifest, indent=2) + "\n"
    for name, text in files.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != text.encode("utf-8"):
            raise ValueError(f"Conflicting content already exists at {path}; use a new directory")
        path.write_bytes(text.encode("utf-8"))
    return manifest
