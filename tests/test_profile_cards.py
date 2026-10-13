"""Profile cards: one card per distinct claim description, most common first."""

from datetime import date

import duckdb
import pytest

from claims.corpus.cards import (
    AMOUNT_EDGES,
    DELAY_EDGES,
    TENURE_EDGES,
    amount_band,
    delay_band,
    tenure_band,
)
from claims.corpus.profile_cards import (
    balanced_order,
    band_sql,
    build_profile_corpus,
    description_counts,
    profile_sentence,
    select_profiles,
)
from claims.history.dataset import ClaimsStore

CUTOFF = date(2026, 1, 1)
# (claim_type, state, amount, prior claims, claims, approved among them, days to resolution)
GROUPS = [
    ("auto", "TX", 3000.0, 0, 40, 30, 10.0),
    ("home", "CA", 3000.0, 0, 25, 5, 20.0),
    ("auto", "CA", 90000.0, 2, 10, 10, 30.0),
    ("renters", "TX", 3000.0, 0, 3, 3, 8.0),
]


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.parquet"
    connection = duckdb.connect()
    connection.execute("""
        CREATE TABLE claims(claim_id VARCHAR, policy_id VARCHAR, claim_type VARCHAR, state VARCHAR,
          policyholder_tenure_years DOUBLE, previous_claims_count INTEGER, incident_date DATE,
          claim_filed_date DATE, claim_amount DOUBLE, deductible DOUBLE, claim_status VARCHAR,
          days_to_resolution DOUBLE, is_fraud_flagged_ground_truth BOOLEAN)
    """)
    rows, n = [], 0

    def add(kind, state, amount, prior, status, days, filed="2023-01-03"):
        nonlocal n
        n += 1
        rows.append((f"CLM-{n:010d}", "POL-100000001", kind, state, 4.0, prior, "2023-01-01",
                     filed, amount, 500.0, status, days, True))

    for kind, state, amount, prior, count, approved, days in GROUPS:
        for i in range(count):
            add(kind, state, amount, prior, "approved" if i < approved else "denied", days)
    # Never eligible: still open, no duration, or closing on or after the cutoff.
    for _ in range(7):
        add("auto", "TX", 3000.0, 0, "pending", float("nan"))
    for _ in range(5):
        add("auto", "TX", 3000.0, 0, "approved", 10.0, filed="2025-12-30")
    connection.executemany("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    connection.execute("COPY claims TO ? (FORMAT PARQUET)", [str(path)])
    connection.close()
    store = ClaimsStore(path, memory_limit="256MB", threads=1)
    yield store
    store.close()


def test_most_common_descriptions_come_first_with_one_exemplar_each(source):
    rows = select_profiles(source, budget=3, cutoff=CUTOFF)
    assert [r["profile_claims"] for r in rows] == [40, 25, 10]
    assert [(r["claim_type"], r["state"]) for r in rows] == [("auto", "TX"), ("home", "CA"), ("auto", "CA")]
    assert len({r["claim_id"] for r in rows}) == 3
    assert rows[0]["profile_approved_share"] == pytest.approx(0.75)
    assert rows[1]["profile_approved_share"] == pytest.approx(0.2)
    assert rows[0]["profile_median_days"] == 10.0


def test_selection_is_deterministic_and_respects_the_budget(source):
    first = [r["claim_id"] for r in select_profiles(source, budget=2, cutoff=CUTOFF)]
    again = [r["claim_id"] for r in select_profiles(source, budget=2, cutoff=CUTOFF)]
    assert first == again and len(first) == 2


def test_open_undated_and_late_closing_claims_are_never_counted(source):
    counts = description_counts(source, CUTOFF)
    assert sum(c["n"] for c in counts) == sum(g[4] for g in GROUPS)
    assert len(counts) == len(GROUPS)


@pytest.mark.parametrize(
    ("edges", "label", "values"),
    [
        (AMOUNT_EDGES, amount_band, [0, 999.99, 1000, 2499.99, 2500, 99_999, 100_000, 250_000, 1e7]),
        (TENURE_EDGES, tenure_band, [0, 0.99, 1, 2.99, 3, 4.99, 5, 9.99, 10, 19.99, 20, 60]),
        (DELAY_EDGES, delay_band, [0, 1, 3, 4, 7, 8, 14, 15, 30, 31, 60, 61, 400]),
    ],
)
def test_sql_bands_agree_with_the_python_bands_used_in_card_text(edges, label, values):
    connection = duckdb.connect()
    literals = ",".join(f"({float(v)}::DOUBLE)" for v in values)
    sql = band_sql("x", edges)
    index = dict(connection.execute(f"SELECT x, {sql} FROM (VALUES {literals}) t(x)").fetchall())
    connection.close()
    seen = {}
    for value in values:
        # The same SQL index must always mean the same card wording, and different indexes differ.
        seen.setdefault(index[float(value)], set()).add(label(value if label is not delay_band else int(value)))
    assert all(len(words) == 1 for words in seen.values())
    assert len({next(iter(words)) for words in seen.values()}) == len(seen)


def test_cards_state_only_dataset_counts_never_coverage_or_eligibility():
    text = profile_sentence(12_345, 0.812, 23.6)
    assert text == (
        "Profile: 12,345 settled claims in the dataset share this description; "
        "81% were approved and the median time to settle was 24 days."
    )
    assert not any(word in text.lower() for word in ("claimable", "eligible", "covered", "valid"))


def test_build_writes_labelled_cards_batches_procedures_and_measured_coverage(source, tmp_path):
    output = tmp_path / "corpus"
    manifest = build_profile_corpus(source, output, budget=3, batch_cards=2)
    assert manifest["cards"] == 3 and len(manifest["batches"]) == 2
    assert [b["cards"] for b in manifest["batches"]] == [2, 1]
    coverage = manifest["coverage"]
    assert coverage["eligible_claims"] == 78
    assert coverage["claims_whose_exact_description_has_a_card"] == 75
    assert coverage["share_of_eligible_claims"] == pytest.approx(75 / 78)
    assert coverage["distinct_descriptions"] == 4 and coverage["smallest_profile_claims"] == 10

    connection = duckdb.connect()
    cursor = connection.execute("SELECT * FROM read_parquet(?)", [str(output / "claim_cards.parquet")])
    names = [d[0] for d in cursor.description]
    records = [dict(zip(names, row)) for row in cursor.fetchall()]
    connection.close()
    assert "policy_id" not in names and "is_fraud_flagged_ground_truth" not in names
    # Default format: only what a query can state, with no outcome and no group profile.
    assert manifest["card_format"] == "description"
    assert all("Profile:" not in r["card_text"] and "Outcome" not in r["card_text"] for r in records)
    assert all(r["card_text"].startswith(f"## history:{r['claim_ref']}\nclaim_ref: {r['claim_ref']}\n") for r in records)
    assert all("POL-" not in r["card_text"] and "fraud" not in r["card_text"] for r in records)

    first = (output / manifest["batches"][0]["path"]).read_text(encoding="utf-8")
    assert first.startswith("# Historical claim cards; corpus batch cardpack_")
    assert manifest["batches"][0]["path"] == "cards/profile-0001.txt"
    assert len(manifest["procedures"]) == 5
    assert all((output / p).is_file() for p in manifest["procedures"])


def test_the_profile_format_still_reproduces_the_first_corpus(source, tmp_path):
    manifest = build_profile_corpus(source, tmp_path / "corpus", budget=3, batch_cards=2, card_format="profile")
    cursor = duckdb.connect().execute(
        "SELECT card_text FROM read_parquet(?) ORDER BY profile_claims DESC", [str(tmp_path / "corpus" / "claim_cards.parquet")]
    )
    first = cursor.fetchall()[0][0]
    assert manifest["card_format"] == "profile"
    assert "Profile: 40 settled claims in the dataset share this description; 75% were approved" in first
    assert "Outcome " in first


def test_balanced_order_makes_every_prefix_span_the_groups():
    records = [
        {"claim_id": f"CLM-{i:010d}", "claim_type": kind, "state": state, "profile_claims": n}
        for i, (kind, state, n) in enumerate(
            [("auto", "CA", 90), ("auto", "CA", 80), ("auto", "CA", 70), ("auto", "TX", 60),
             ("home", "CA", 50), ("home", "TX", 40), ("auto", "TX", 30)]
        )
    ]
    ordered = balanced_order(records)
    assert sorted(r["claim_id"] for r in ordered) == sorted(r["claim_id"] for r in records)
    # The first round holds the best card of each (type, state) group; later rounds the runners-up.
    first_round = {(r["claim_type"], r["state"]) for r in ordered[:4]}
    assert first_round == {("auto", "CA"), ("auto", "TX"), ("home", "CA"), ("home", "TX")}
    # Within a round: by state, then type (CA auto, CA home, TX auto, TX home).
    assert [r["profile_claims"] for r in ordered[:4]] == [90, 50, 60, 40]
    assert [r["profile_claims"] for r in ordered[4:]] == [80, 30, 70]
    assert balanced_order(list(reversed(records))) == ordered  # independent of input order


def test_the_default_build_is_balanced_and_the_order_is_recorded(source, tmp_path):
    manifest = build_profile_corpus(source, tmp_path / "balanced", budget=4, batch_cards=4)
    assert manifest["order"] == "balanced"
    common = build_profile_corpus(source, tmp_path / "common", budget=4, batch_cards=4, order="common_first")
    assert common["order"] == "common_first"
    with pytest.raises(ValueError, match="order"):
        build_profile_corpus(source, tmp_path / "bad", budget=4, order="random")


def test_an_unknown_card_format_is_refused(source, tmp_path):
    with pytest.raises(ValueError, match="card_format"):
        build_profile_corpus(source, tmp_path / "corpus", budget=1, card_format="whole")


def test_build_refuses_a_non_empty_output_directory(source, tmp_path):
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "something.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        build_profile_corpus(source, tmp_path / "corpus", budget=2)


def test_per_type_mode_gives_every_claim_type_its_most_common_descriptions(source):
    rows = select_profiles(source, per_type=1, cutoff=CUTOFF)
    assert [(r["claim_type"], r["profile_claims"]) for r in rows] == [("auto", 40), ("home", 25), ("renters", 3)]
    # auto's second description (10 claims) is dropped even though it is more common than renters'.
    assert all(not (r["claim_type"] == "auto" and r["profile_claims"] == 10) for r in rows)


def test_per_type_build_measures_coverage_for_each_claim_type(source, tmp_path):
    manifest = build_profile_corpus(source, tmp_path / "corpus", per_type=1, batch_cards=10)
    by_type = manifest["coverage"]["by_claim_type"]
    assert by_type["auto"] == {"cards": 1, "eligible_claims": 50, "share_with_an_exact_twin": pytest.approx(0.8)}
    assert by_type["home"]["share_with_an_exact_twin"] == 1.0
    assert manifest["selection"]["cards_per_type"] == 1 and manifest["cards"] == 3


def test_exactly_one_allocation_rule_must_be_chosen(source):
    with pytest.raises(ValueError, match="exactly one"):
        select_profiles(source, cutoff=CUTOFF)
    with pytest.raises(ValueError, match="exactly one"):
        select_profiles(source, budget=3, per_type=1, cutoff=CUTOFF)
