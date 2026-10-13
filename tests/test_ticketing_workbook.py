"""The claims-as-tickets workbook uploaded through Synapt's Ticketing option.

A first upload was rejected because a column name was not a plain identifier, so the header rule is pinned here, together with
what a ticket may and may not carry: no outcome words in the text Synapt embeds, no policy ID, and one unique ticket ID each.
"""

import importlib.util
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

spec = importlib.util.spec_from_file_location(
    "make_ticketing_sample", Path(__file__).parents[1] / "scripts" / "make_ticketing_sample.py"
)
tickets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tickets)

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
KINDS = ("auto", "home", "renters", "property", "business")


def claim(n, kind="auto", flagged=False):
    return {
        "claim_id": f"CLM-{n:06d}", "policy_id": f"POL-SECRET-{n}", "claim_type": kind, "state": "TX",
        "claim_filed_date": "2024-03-10", "incident_date": "2024-03-01", "claim_amount": 12400.0 + n, "deductible": 500.0,
        "policyholder_tenure_years": 2.4, "previous_claims_count": 1, "claim_status": "denied" if flagged else "approved",
        "days_to_resolution": 12.0, "is_fraud_flagged_ground_truth": flagged,
    }


class FakeStore:
    """Hands back a fixed pool in a fixed order, as the hash-ordered query would."""

    source = "claims"

    def __init__(self, pool):
        self.pool = pool

    def rows(self, sql, params):
        return list(self.pool)


def pool(per_kind=30, flagged_every=10):
    return [claim(i * 10 + k, kind, flagged=i % flagged_every == 0) for k, kind in enumerate(KINDS) for i in range(per_kind)]


def read_back(path):
    with zipfile.ZipFile(path) as z:
        shared = [si.find("m:t", NS).text or "" for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS)]
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.find("m:sheetData", NS).findall("m:row", NS):
        rows.append([shared[int(c.find("m:v", NS).text)] if c.get("t") == "s" else float(c.find("m:v", NS).text) for c in row.findall("m:c", NS)])
    return rows[0], rows[1:]


def test_the_column_names_are_plain_identifiers_which_is_what_synapt_requires():
    assert all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in tickets.COLUMNS)
    assert len(set(tickets.COLUMNS)) == len(tickets.COLUMNS)


def test_a_stratified_sample_has_exactly_the_requested_flagged_share_per_type():
    rows = tickets.sample_rows(FakeStore(pool()), per_type=10, flagged_per_type=3, seed=1)
    assert len(rows) == 50
    for kind in KINDS:
        of_kind = [r for r in rows if r["claim_type"] == kind]
        assert len(of_kind) == 10 and sum(r["is_fraud_flagged_ground_truth"] for r in of_kind) == 3


def test_a_natural_sample_takes_the_first_rows_in_order_and_does_not_choose_labels():
    rows = tickets.sample_rows(FakeStore(pool()), per_type=10, flagged_per_type=None, seed=1)
    expected = [r for kind in KINDS for r in [r for r in pool() if r["claim_type"] == kind][:10]]
    assert sorted(r["claim_id"] for r in rows) == sorted(r["claim_id"] for r in expected)
    assert sum(r["is_fraud_flagged_ground_truth"] for r in rows) == 5  # one in ten, as the pool has it, not a quota


def test_a_pool_too_small_for_the_request_stops_instead_of_writing_a_short_file():
    with pytest.raises(SystemExit):
        tickets.sample_rows(FakeStore(pool(per_kind=5)), per_type=10, flagged_per_type=None, seed=1)
    with pytest.raises(SystemExit):
        tickets.sample_rows(FakeStore(pool(per_kind=30, flagged_every=1000)), per_type=10, flagged_per_type=3, seed=1)


def test_the_workbook_reads_back_with_unique_ids_no_outcome_in_the_embedded_text_and_no_policy_id(tmp_path):
    rows = tickets.sample_rows(FakeStore(pool()), per_type=10, flagged_per_type=None, seed=1)
    target = tmp_path / "t.xlsx"
    tickets.write_xlsx(target, tickets.COLUMNS, [tickets.ticket(r) for r in rows])
    header, body = read_back(target)
    assert tuple(header) == tickets.COLUMNS and len(body) == 50
    col = {name: i for i, name in enumerate(header)}
    ids = [r[col["ticket_id"]] for r in body]
    assert len(set(ids)) == len(ids) and all(i.startswith("claimref_") for i in ids)
    embedded = [r[col[name]] for r in body for name in ("title", "description", "category", "region")]
    assert not [t for t in embedded if re.search(r"approved|denied|settled|fraud|flagged|median", t, re.IGNORECASE)]
    assert not any("POL-" in str(v) or "SECRET" in str(v) or "CLM-" in str(v) for r in body for v in r)  # no policy ID, no raw claim ID
    assert {r[col["resolution"]] for r in body} <= {"approved", "denied"}
    assert {r[col["fraud_flag"]] for r in body} <= {"flagged", "not_flagged"}
