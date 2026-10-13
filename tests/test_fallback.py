"""Degraded mode: after a real Synapt failure the service keeps working from a local copy, and says so."""

import zlib
from contextlib import asynccontextmanager

import duckdb
import numpy as np
import pytest
from fastapi.testclient import TestClient

from claims.api.main import create_app
from claims.core.demo_cases import DEMO_CASES
from claims.core.schemas import ClaimInput
from claims.core.settings import Settings
from claims.corpus.builder import SOPS, sop_document
from claims.corpus.cards import claim_alias
from claims.retrieval.fallback import DEGRADED_NOTICE, LocalKnowledge, description_of
from claims.synapt.adapter import LiveSynaptAdapter

CREDENTIALS = {"synapt_username": "u", "synapt_password": "p", "synapt_provider_id": "prov"}
CARDS = [
    ("CLM-0000000001", "auto claim in regionkey_aa. Claimed amount band 5,000-10,000 USD (about $7,000); deductible $500."),
    ("CLM-0000000002", "auto claim in regionkey_aa. Claimed amount band 10,000-25,000 USD (about $20,000); deductible $1,000."),
    ("CLM-0000000003", "home claim in regionkey_ab. Claimed amount band 25,000-50,000 USD (about $30,000); deductible $2,000."),
    ("CLM-0000000004", "renters claim in regionkey_ac. Claimed amount band 1,000-2,500 USD (about $2,000); deductible $250."),
]


class WordHashEmbedder:
    """A deterministic stand-in for the embedding model: counts of hashed words, so shared words mean similarity."""

    def __init__(self):
        self.documents_embedded = 0

    def embed(self, texts):
        for text in texts:
            self.documents_embedded += 1
            vector = np.zeros(64, dtype=np.float32)
            for word in text.lower().replace(".", " ").replace(",", " ").split():
                vector[zlib.crc32(word.encode()) % 64] += 1
            yield vector


def make_cards(path):
    tail = (
        "Outcome approved after 12 days. Profile: 1,000 settled claims in the dataset share this description; "
        "90% were approved and the median time to settle was 20 days."
    )
    rows = [
        (cid, f"## history:{claim_alias(cid)}" + chr(10) + f"claim_ref: {claim_alias(cid)}" + chr(10) + f"{text} {tail}" + chr(10))
        for cid, text in CARDS
    ]
    connection = duckdb.connect()
    connection.execute("CREATE TABLE c(claim_id VARCHAR, card_text VARCHAR)")
    connection.executemany("INSERT INTO c VALUES (?, ?)", rows)
    connection.execute("COPY c TO ? (FORMAT PARQUET)", [str(path)])
    connection.close()


@pytest.fixture
def settings(tmp_path):
    make_cards(tmp_path / "claim_cards.parquet")
    return Settings(
        _env_file=None, claims_fallback_enabled=True,
        claims_fallback_cards_path=tmp_path / "claim_cards.parquet",
        claims_fallback_index_dir=tmp_path / "index",
        claims_search_cache_dir=tmp_path / "no-model-here",
        claims_database_path=tmp_path / "runtime.sqlite", claims_data_path=tmp_path / "missing.json",
        claims_artifact_dir=tmp_path / "models", **CREDENTIALS,
    )


def claim(**overrides):
    return ClaimInput.model_validate(DEMO_CASES[0]["claim"] | overrides)


def test_only_the_description_is_indexed_not_the_header_outcome_or_profile():
    card = ("## history:claimref_aaa\nclaim_ref: claimref_aaa\nauto claim in regionkey_aa. Filed 9 days after. "
            "Outcome approved after 12 days. Profile: 5 settled claims share this.\n")
    assert description_of(card) == "auto claim in regionkey_aa. Filed 9 days after."


def test_the_five_procedures_are_the_same_text_that_was_uploaded_and_are_labelled_local():
    procedures = LocalKnowledge.procedures()
    assert [p.source_id for p in procedures] == [f"local:{sid}" for sid, _, _ in SOPS]
    assert all(p.provenance == "local_copy" for p in procedures)
    assert procedures[0].text == sop_document(*SOPS[0])


def test_retrieval_returns_a_degraded_bundle_with_the_closest_cards_first(settings):
    knowledge = LocalKnowledge(settings, embedder=WordHashEmbedder())
    bundle = knowledge.retrieve(claim(claim_type="auto", state="CA"))
    assert bundle.mode == "degraded" and bundle.warnings == [DEGRADED_NOTICE]
    assert len(bundle.evidence) == 5 and not any(e.provenance == "synapt" for e in bundle.evidence)
    assert len(bundle.semantic_claim_ids) == len(CARDS)
    assert set(bundle.semantic_claim_ids[:2]) == {"CLM-0000000001", "CLM-0000000002"}


def test_the_index_is_cached_and_reloaded_without_embedding_the_cards_again(settings):
    first = WordHashEmbedder()
    LocalKnowledge(settings, embedder=first).warm()
    assert first.documents_embedded == len(CARDS)
    assert list(settings.claims_fallback_index_dir.glob("*.npy"))
    second = WordHashEmbedder()
    knowledge = LocalKnowledge(settings, embedder=second)
    knowledge.warm()
    assert second.documents_embedded == 0 and knowledge.backend == "embeddings"


def test_without_the_embedding_model_a_tfidf_index_still_ranks_cards(settings):
    knowledge = LocalKnowledge(settings)  # the model directory does not exist
    ids = knowledge.search("home claim in regionkey_ab. Claimed amount band 25,000-50,000 USD", 2)
    assert knowledge.backend == "tfidf" and ids[0] == "CLM-0000000003"


def test_it_is_unavailable_when_disabled_or_when_the_card_file_is_missing(settings, tmp_path):
    assert LocalKnowledge(settings).available()
    assert not LocalKnowledge(settings.model_copy(update={"claims_fallback_enabled": False})).available()
    assert not LocalKnowledge(settings.model_copy(update={"claims_fallback_cards_path": tmp_path / "nope.parquet"})).available()


def synapt_down(settings, monkeypatch):
    adapter = LiveSynaptAdapter(settings)

    @asynccontextmanager
    async def down():
        raise ConnectionError("unreachable")
        yield

    monkeypatch.setattr(adapter, "_session", down)
    return adapter


def test_when_synapt_fails_the_run_completes_in_degraded_mode_and_says_so(settings, monkeypatch):
    app = create_app(settings, adapter=synapt_down(settings, monkeypatch),
                     fallback=LocalKnowledge(settings, embedder=WordHashEmbedder()))
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
        search = client.post("/api/search", json={"claim": DEMO_CASES[0]["claim"]})
        assert app.state.service.last_retrieval == "local_fallback"
    assert run["status"] in ("awaiting_review", "needs_manual_review") and run["mode"] == "degraded"
    provenance = {e["provenance"] for e in run["evidence"]}
    assert "local_copy" in provenance and "synapt" not in provenance
    assert any(f["kind"] == "limitation" and f["text"] == DEGRADED_NOTICE for f in run["findings"])
    assert search.status_code == 200 and search.json()["mode"] == "degraded"


def test_a_healthy_synapt_is_still_used_and_the_run_is_not_degraded(settings):
    app = create_app(settings, fallback=LocalKnowledge(settings, embedder=WordHashEmbedder()))
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
        assert app.state.service.last_retrieval == "synapt"
    assert run["mode"] == "live" and not any(e["provenance"] == "local_copy" for e in run["evidence"])


def test_with_no_local_copy_a_synapt_failure_still_fails_the_run(settings, monkeypatch):
    unavailable = settings.model_copy(update={"claims_fallback_enabled": False})
    app = create_app(unavailable, adapter=synapt_down(unavailable, monkeypatch))
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
    assert run["status"] == "failed" and not run.get("evidence")
