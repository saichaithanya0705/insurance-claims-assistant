"""DuckDB-backed access to a Parquet claims file, using a small generated file."""

from datetime import date

import duckdb
import pytest

from claims.core.schemas import ClaimInput, SearchFilters
from claims.corpus.builder import (
    batch_header,
    build_corpus,
    make_batches,
    render_card,
    select_cards,
)
from claims.corpus.cards import claim_alias
from claims.history.dataset import ClaimsStore
from claims.history.retriever import HistoricalRetriever

TYPES = ("auto", "home", "renters", "property", "business")


@pytest.fixture
def parquet(tmp_path):
    """3,000 deterministic claims; pending rows carry NaN (not NULL) durations, as the real file."""
    path = tmp_path / "claims.parquet"
    duckdb.connect().execute(
        f"""
        COPY (
          SELECT
            printf('CLM-%010d', i) AS claim_id,
            printf('POL-%09d', 100000000 + i % 2900) AS policy_id,
            (['auto','home','renters','property','business'])[1 + i % 5] AS claim_type,
            (['TX','CA','FL','NY'])[1 + (hash(i + 1) % 4)::INTEGER] AS state,
            ((i % 30) * 1.0)::FLOAT AS policyholder_tenure_years,
            (i % 5)::INTEGER AS previous_claims_count,
            (DATE '2024-01-01' + CAST(i % 400 AS INTEGER)) AS incident_date,
            (DATE '2024-01-01' + CAST(i % 400 AS INTEGER) + CAST(i % 7 AS INTEGER)) AS claim_filed_date,
            (1000 + (i * 137) % 50000)::DOUBLE AS claim_amount,
            500::DOUBLE AS deductible,
            (['approved','approved','approved','approved','approved','approved','denied','denied',
              'pending','under_review'])[1 + (hash(i) % 10)::INTEGER] AS claim_status,
            CASE WHEN hash(i) % 10 = 8 THEN 'NaN'::FLOAT ELSE (5 + i % 20)::FLOAT END AS days_to_resolution,
            (i % 13 = 0) AS is_fraud_flagged_ground_truth
          FROM range(3000) t(i)
        ) TO '{path.as_posix()}' (FORMAT PARQUET)
        """
    )
    return path


@pytest.fixture
def store(parquet):
    opened = ClaimsStore(parquet)
    yield opened
    opened.close()


def claim(**changes):
    values = {
        "description": "Vehicle damage after a collision",
        "claim_type": "auto",
        "state": "TX",
        "incident_date": "2025-06-01",
        "claim_filed_date": "2025-06-03",
        "claim_amount": 8000,
        "deductible": 500,
        "previous_claims_count": 1,
        "policyholder_tenure_years": 4,
    }
    return ClaimInput.model_validate(values | changes)


def test_row_count_and_fingerprint_are_cached(store, parquet):
    assert store.row_count() == 3000
    fingerprint = store.fingerprint()
    assert fingerprint["rows"] == 3000 and len(fingerprint["source_file_sha256"]) == 64
    assert parquet.with_name(parquet.name + ".fingerprint.json").exists()
    assert ClaimsStore(parquet).fingerprint()["source_file_sha256"] == fingerprint["source_file_sha256"]


def test_missing_file_and_unsafe_path_are_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        ClaimsStore(tmp_path / "absent.parquet")
    quoted = tmp_path / "it's.parquet"
    quoted.write_bytes(b"x")
    with pytest.raises(ValueError):
        ClaimsStore(quoted)


def test_candidates_are_only_settled_claims_closed_before_filing(store):
    new = claim()
    rows = store.candidates(new, SearchFilters(), limit=500)
    assert rows
    for row in rows:
        assert row["claim_status"] in ("approved", "denied")
        # NaN (pending) durations never leak in as a closed claim.
        assert row["days_to_resolution"] is not None
        closed = date.fromisoformat(row["claim_filed_date"]).toordinal() + int(row["days_to_resolution"])
        assert closed < new.claim_filed_date.toordinal()


def test_every_filter_dimension_is_applied(store):
    new = claim()
    rows = store.candidates(
        new,
        SearchFilters(
            claim_type="home",
            state="CA",
            claim_status="denied",
            min_amount=5000,
            max_amount=30000,
            min_previous_claims=1,
            max_previous_claims=3,
        ),
        limit=500,
    )
    for row in rows:
        assert row["claim_type"] == "home" and row["state"] == "CA"
        assert row["claim_status"] == "denied"
        assert 5000 <= row["claim_amount"] <= 30000
        assert 1 <= row["previous_claims_count"] <= 3
    assert store.candidates(new, SearchFilters(state="AK")) == []


def test_candidate_pool_is_the_claims_own_type_unless_filtered(store):
    assert {r["claim_type"] for r in store.candidates(claim(), SearchFilters(), limit=300)} == {"auto"}
    other = store.candidates(claim(), SearchFilters(claim_type="home"), limit=300)
    assert {r["claim_type"] for r in other} == {"home"}


def test_open_statuses_are_searchable_and_have_no_outcome(store):
    pending = store.candidates(claim(), SearchFilters(claim_status="pending"), limit=300)
    assert pending and all(r["claim_status"] == "pending" for r in pending)
    assert all(r["days_to_resolution"] is None for r in pending)  # NaN cleaned to None
    review = store.candidates(claim(), SearchFilters(claim_status="under_review"), limit=300)
    assert review and all(r["claim_status"] == "under_review" for r in review)
    # They must already have been on file before the new claim was filed.
    assert all(r["claim_filed_date"] < "2025-06-03" for r in pending + review)


def test_semantic_ids_are_honoured_only_under_the_same_filters(store):
    new = claim()
    anchor = store.candidates(new, SearchFilters(), limit=300)[-1]["claim_id"]
    found = store.candidates(new, SearchFilters(), ids=[anchor, "CLM-9999999999"])
    assert [r["claim_id"] for r in found] == [anchor]
    assert store.candidates(new, SearchFilters(state="AK"), ids=[anchor]) == []


def test_sample_is_repeatable_and_clean(store):
    first, second = store.sample(500, seed=7), store.sample(500, seed=7)
    assert [r["claim_id"] for r in first] == [r["claim_id"] for r in second]
    assert len(first) == 500
    assert all(isinstance(r["incident_date"], str) and len(r["incident_date"]) == 10 for r in first)
    assert any(r["days_to_resolution"] is None for r in store.sample(3000, seed=1))


def test_retriever_uses_parquet_and_fuses_semantic_rank(parquet, tmp_path):
    retriever = HistoricalRetriever(tmp_path / "missing.json", parquet)
    assert retriever.store is not None and retriever.origin == "published_synthetic_dataset"
    new = claim()
    base = retriever.search(new, SearchFilters(), top_k=5)
    assert len(base) == 5 and all("dataset_fraud_flag" in c for c in base)
    # A card Synapt ranks first lifts a mid-ranked eligible case. Reciprocal-rank fusion does not
    # let one list outvote a claim ranked first in both of the others, so it rises, not leaps to #1.
    ranked = [c["claim_id"] for c in retriever.search(new, SearchFilters(), top_k=20)]
    target = ranked[12]
    fused = retriever.search(new, SearchFilters(), top_k=20, semantic_ids=[target])
    position = [c["claim_id"] for c in fused].index(target)
    assert position < 12 and fused[position]["semantic_match"]
    # ...and a semantic match never overrides a filter.
    assert not retriever.search(new, SearchFilters(state="AK"), semantic_ids=[target])
    pending = retriever.search(new, SearchFilters(claim_status="pending"))
    assert pending and all(c["open_case"] and c["days_to_resolution"] is None for c in pending)
    retriever.close()


def test_selection_is_stratified_deterministic_and_closed_before_cutoff(store):
    first = select_cards(store, 40, date(2025, 1, 1))
    assert first == select_cards(store, 40, date(2025, 1, 1))
    assert [sum(r["claim_type"] == t for r in first) for t in sorted(TYPES)] == [40] * 5
    assert all(r["claim_status"] in ("approved", "denied") for r in first)
    assert all(
        date.fromisoformat(r["claim_filed_date"]).toordinal() + int(r["days_to_resolution"])
        < date(2025, 1, 1).toordinal()
        for r in first
    )
    with pytest.raises(ValueError):
        select_cards(store, 100_000_000, date(2025, 1, 1))


def test_cards_batches_and_manifest_never_leak_labels_or_identifiers(store, tmp_path):
    manifest = build_corpus(store, tmp_path / "corpus", per_type=30, cutoff=date(2025, 1, 1))
    assert manifest["cards"] == 150 and sum(manifest["cards_by_type"].values()) == 150
    texts = [(tmp_path / "corpus" / b["path"]).read_text(encoding="utf-8") for b in manifest["batches"]]
    for batch, text in zip(manifest["batches"], texts):
        assert len(text.encode("utf-8")) == batch["bytes"] <= 60 * 1024
        assert text.count("## history:claimref_") == len(batch["claim_ids"]) <= 100
    joined = "\n".join(texts)
    assert "CLM-" not in joined and "POL-" not in joined and "fraud_flag" not in joined.lower().replace(
        "or fraud label", ""
    )
    assert not any(state in joined for state in ("Texas", "California", "Florida", "(TX)"))
    first_id = manifest["batches"][0]["claim_ids"][0]
    assert claim_alias(first_id) in texts[0]
    # Rebuilding identical content is idempotent; different content in the same place is refused.
    assert build_corpus(store, tmp_path / "corpus", per_type=30, cutoff=date(2025, 1, 1)) == manifest
    with pytest.raises(ValueError, match="Conflicting"):
        build_corpus(store, tmp_path / "corpus", per_type=40, cutoff=date(2025, 1, 1))


def test_batching_respects_limits():
    cards = [({"claim_id": f"CLM-{i:010d}"}, "z" * 400) for i in range(25)]
    batches = make_batches(cards, max_cards=10, max_bytes=3000)
    assert sum(len(batch) for batch in batches) == 25
    for batch in batches:
        size = len(batch_header(9999, 10).encode()) + sum(len(t) + 1 for _, t in batch)
        assert len(batch) <= 10 and size <= 3000
    with pytest.raises(ValueError):
        make_batches(cards, max_cards=500, max_bytes=3000)
    with pytest.raises(ValueError):
        make_batches([({}, "z" * 5000)], max_cards=10, max_bytes=3000)


def test_render_card_uses_masking_safe_alias_and_state():
    row = {
        "claim_id": "CLM-0000000012",
        "claim_type": "auto",
        "state": "TX",
        "claim_amount": 8500.0,
        "deductible": 500.0,
        "previous_claims_count": 0,
        "policyholder_tenure_years": 4.0,
        "incident_date": "2025-01-01",
        "claim_filed_date": "2025-01-02",
        "claim_status": "approved",
        "days_to_resolution": 12.0,
    }
    card = render_card(row)
    assert card.startswith("## history:claimref_aaaaaaaabc\nclaim_ref: claimref_aaaaaaaabc\n")
    assert "TX" not in card and "regionkey_" in card


def test_training_samples_the_parquet_and_records_provenance(parquet, tmp_path):
    from claims.ml.analytics import AnalyticsService

    service = AnalyticsService(
        tmp_path / "absent.json", tmp_path / "models", parquet, train_rows=2500
    )
    assert service.status()["data_present"] is True
    report = service.train()
    assert report["available"] and report["valid_rows"] == 2500
    origin = report["origin"]
    assert origin["rows"] == 3000 and origin["sample_rows"] == 2500
    assert "Uniform reservoir sample of 2,500 of 3,000" in origin["sampling"]
    assert len(origin["source_file_sha256"]) == 64
    # Pending rows (NaN durations) never become resolution training examples.
    assert report["metrics"]["resolution"]["counts"]["train"] > 0
    assert all(report["metrics"][t]["available"] for t in ("amount", "resolution", "fraud"))
    # A second service instance loads the saved artifact.
    assert AnalyticsService(tmp_path / "absent.json", tmp_path / "models").status()["available"]


def test_semantic_matches_follow_the_type_pool_and_cannot_displace_strong_matches(parquet, tmp_path):
    retriever = HistoricalRetriever(tmp_path / "missing.json", parquet)
    new = claim()
    # Cards of another claim type are not "similar": they are dropped, and the stats say so.
    other_type = [r["claim_id"] for r in retriever.store.candidates(new, SearchFilters(claim_type="home"), limit=5)]
    result = retriever.search(new, SearchFilters(), top_k=5, semantic_ids=other_type)
    assert all(c["claim_type"] == "auto" and not c["semantic_match"] for c in result)
    assert retriever.last_search == {"semantic_candidates": 5, "semantic_eligible": 0, "semantic_in_results": 0}
    # A poor numeric match at Synapt's rank 1 does not displace the strongest local matches.
    base = [c["claim_id"] for c in retriever.search(new, SearchFilters(), top_k=5)]
    weakest = retriever.store.candidates(new, SearchFilters(), limit=300)[-1]["claim_id"]
    fused = retriever.search(new, SearchFilters(), top_k=5, semantic_ids=[weakest])
    assert [c["claim_id"] for c in fused[:5]] == base
    # ...but it is still shown, clearly labelled as related in meaning rather than closest.
    assert fused[5]["claim_id"] == weakest and fused[5]["surfaced_by"] == "semantic"
    assert fused[5]["semantic_rank"] == 1 and any("ticket store ranked" in r for r in fused[5]["match_reasons"])
    assert all(c["surfaced_by"] == "fusion" for c in fused[:5])
    # A mid-ranked candidate that Synapt also ranks first is lifted and labelled with its rank.
    target = [c["claim_id"] for c in retriever.search(new, SearchFilters(), top_k=20)][12]
    lifted = retriever.search(new, SearchFilters(), top_k=20, semantic_ids=["CLM-9999999999", target])
    case = next(c for c in lifted if c["claim_id"] == target)
    assert case["semantic_match"] and case["semantic_rank"] == 2
    assert retriever.last_search == {"semantic_candidates": 2, "semantic_eligible": 1, "semantic_in_results": 1}


def test_diverse_semantic_outliers_never_outrank_a_homogeneous_pool_of_exact_matches(tmp_path):
    """Regression: with IDF weighting, ~30 near-identical claims share every term (IDF ~ 0) while a
    few diverse Synapt cards carry rare terms, so BM25 ranked the outliers first."""
    import json

    def row(i, state="TX", amount=8500.0, prior=0, tenure=4.0, kind="auto", delay=1):
        return {
            "claim_id": f"CLM-{i:010d}", "policy_id": f"POL-{i}", "claim_type": kind, "state": state,
            "claim_amount": amount + (i % 7), "deductible": 500.0, "previous_claims_count": prior,
            "policyholder_tenure_years": tenure, "incident_date": "2024-03-01",
            "claim_filed_date": f"2024-03-{1 + delay:02d}", "claim_status": "approved",
            "days_to_resolution": 10.0,
        }

    exact = [row(i) for i in range(1, 41)]
    outliers = [
        row(101, "NJ", 3393, 3, 0.5, delay=30), row(102, "UT", 4277, 2, 12, delay=9),
        row(103, "NM", 12296, 4, 25, delay=2), row(104, "OH", 61000, 5, 8, delay=20),
    ]
    path = tmp_path / "pool.json"
    path.write_text(json.dumps({"rows": exact + outliers}))
    retriever = HistoricalRetriever(path)
    ids = [r["claim_id"] for r in outliers]  # Synapt ranks the four outliers 1..4
    result = retriever.search(claim(), SearchFilters(), top_k=5, semantic_ids=ids)
    top, extras = result[:5], result[5:]
    assert all(c["state"] == "TX" and c["previous_claims_count"] == 0 for c in top)
    assert all(c["surfaced_by"] == "fusion" and not c["semantic_match"] for c in top)
    assert [c["claim_id"] for c in extras] == ids[:3]  # best three by Synapt rank, in order
    assert [c["semantic_rank"] for c in extras] == [1, 2, 3]
    assert retriever.last_search == {"semantic_candidates": 4, "semantic_eligible": 4, "semantic_in_results": 3}
