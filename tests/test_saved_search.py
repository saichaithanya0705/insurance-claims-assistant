from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from claims.api.main import create_app
from claims.core.settings import Settings
from claims.storage.run_store import Store
from claims.storage.saved_search import SavedCaseSearch


def record(store, run_id, text, owner=None, title=None):
    store.save(
        run_id,
        {
            "run_id": run_id,
            "title": title,
            "status": "awaiting_review",
            "claim": {
                "description": text,
                "claim_type": "auto",
                "state": "TX",
                "claim_amount": 3000,
            },
        },
    )
    if owner:
        store.set_owner(run_id, owner)


class Embedder:
    def __init__(self):
        self.documents = []

    def passage_embed(self, texts):
        self.documents.extend(texts)
        return [np.array([1, 0] if "car" in text else [0, 1]) for text in texts]

    def query_embed(self, query):
        return [np.array([1, 0])]


def test_literal_ranking_titles_partial_ids_and_semantic_recall(tmp_path):
    store = Store(tmp_path / "cases.sqlite")
    settings = Settings(_env_file=None)
    record(store, "abc-123", "My car was rear-ended", owner="alice")
    record(store, "abc-456", "My house suffered water damage", owner="bob", title="Pipe burst")
    model = Embedder()
    search = SavedCaseSearch(store, settings, model)
    assert [item["run_id"] for item in search.suggest("abc")["items"]] == ["abc-456", "abc-123"]
    assert search.suggest("ABC-123")["items"][0]["match_kind"] == "Exact ID"
    assert search.suggest("pipe")["items"][0]["match_kind"] == "Title match"
    # Punctuation is normalized for text, but UUID matching stays literal.
    assert search.suggest("rear ended")["items"][0]["match_kind"] == "Title match"
    related = search.suggest("vehicle collision", owner_id="alice")
    assert related["items"][0]["run_id"] == "abc-123"
    assert related["items"][0]["match_kind"] == "Related meaning"
    before = len(model.documents)
    search.suggest("vehicle collision", owner_id="alice")
    assert len(model.documents) == before
    record(store, "abc-123", "The house roof collapsed", owner="alice")
    assert search.suggest("vehicle collision", owner_id="alice")["items"] == []
    assert len(model.documents) == before + 1
    assert search.suggest("abc", owner_id="alice")["total"] == 1
    assert search.suggest("abc", owner_id="charlie")["total"] == 0
    store.close()


def test_invalid_embeddings_fail_to_literal_matches(tmp_path):
    store = Store(tmp_path / "cases.sqlite")
    record(store, "car-1", "car accident")
    model = Embedder()
    model.passage_embed = lambda texts: [np.array([float("nan"), 0])]
    result = SavedCaseSearch(store, Settings(_env_file=None), model).suggest("car accident")
    assert result["items"][0]["run_id"] == "car-1"
    assert result["items"][0]["match_kind"] == "Title match"
    assert result["semantic_status"] == "unavailable"
    store.close()


def test_suggestions_route_boundaries_and_api_key(tmp_path):
    settings = Settings(
        _env_file=None,
        claims_database_path=tmp_path / "cases.sqlite",
        claims_data_path=Path("absent.json"),
        claims_search_enabled=False,
        claims_api_key="suggestions-test-key",
    )
    app = create_app(settings)
    record(app.state.service.store, "prefix-abc", "Windshield shattered")
    with TestClient(app) as client:
        assert client.get("/api/case-suggestions").status_code == 401
        headers = {"X-Claims-Api-Key": "suggestions-test-key"}
        assert (
            client.get("/api/case-suggestions?q=prefix", headers=headers).json()["items"][0][
                "run_id"
            ]
            == "prefix-abc"
        )
        for query in ("limit=0", "limit=21", "q=" + "x" * 301):
            assert client.get("/api/case-suggestions?" + query, headers=headers).status_code == 422


def test_default_database_bootstraps_without_overwriting_existing_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    template = Store(Path("data/bootstrap/claims.sqlite"))
    record(template, "portable-case", "Saved car incident")
    template.close()
    default = Store(Path("data/runtime/claims.sqlite"))
    assert default.get("portable-case")["claim"]["description"] == "Saved car incident"
    record(default, "local-case", "Another incident")
    default.close()
    reopened = Store(Path("data/runtime/claims.sqlite"))
    assert reopened.search()["total"] == 2
    reopened.close()
    custom = Store(Path("custom.sqlite"))
    assert custom.search()["total"] == 0
    custom.close()
