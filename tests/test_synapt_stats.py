"""The Connection page's "what the knowledge base holds" figures: read-only, cached, and never an error page."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from claims.api.main import create_app
from claims.core.settings import Settings
from claims.synapt.stats import SynaptStats, summarize

STATS = {
    "doc_count": 38, "nodes": 10_314, "chunks": 10_038, "entities": 117, "concepts": 6, "propositions": 0,
    "procedures": 21, "edges": 10_598, "provider_kind": "knowledge", "has_ticket_store": False,
    "counts_by_label": {
        "Concept": 6, "Step": 93, "Entity": 67, "Chunk": 10_038, "Document": 38, "Procedure": 21, "Provider": 1,
        "BusinessProcess": 35, "Objective": 8, "Organization": 3, "Product": 2, "Customer": 2,
    },
}
EPISODES = {"mode": "inspect", "provider_id": "p1", "store": {"collection": "es_p1", "exists": True, "episode_count": 1}}


class Reader:
    """Serves what trident_get_stats and trident_episodes return; refuses every other tool."""

    def __init__(self, stats=STATS, episodes=EPISODES, fail=None):
        self.stats, self.episodes, self.fail, self.calls = stats, episodes, fail, []

    async def call_read_tool(self, name, arguments, **_):
        assert name in {"trident_get_stats", "trident_episodes"}, "read-only tools only"
        assert arguments == {"provider_id": "p1"}, "every read is scoped to the provider"
        self.calls.append(name)
        if self.fail and name in self.fail:
            raise RuntimeError("Synapt down")
        return {"result": json.dumps(self.stats if name == "trident_get_stats" else self.episodes)}


class Clock:
    def __init__(self):
        self.now = 1_000.0

    def __call__(self):
        return self.now


def test_the_figures_are_the_providers_own_and_the_knowledge_list_leaves_out_the_text_itself():
    out = summarize(STATS | {"provider_id": "p1"}, EPISODES, "2026-10-12T00:00:00+00:00")
    assert out["available"] is True and out["provider_id"] == "p1" and out["kind"] == "knowledge"
    assert (out["documents"], out["passages"], out["graph_nodes"], out["connections"]) == (38, 10_038, 10_314, 10_598)
    assert (out["procedures"], out["steps"], out["entities"], out["concepts"]) == (21, 93, 117, 6)
    assert out["has_ticket_store"] is False and out["episodes"] == {"store_exists": True, "count": 1}
    kinds = out["knowledge_by_kind"]
    assert kinds[0] == {"kind": "Step", "count": 93}  # biggest first
    assert not {"Chunk", "Document", "Provider"} & {k["kind"] for k in kinds}
    # the entity-like kinds add up to the provider's own entity figure, so the tiles and the list agree
    assert sum(k["count"] for k in kinds if k["kind"] in {"Entity", "BusinessProcess", "Objective", "Organization", "Product", "Customer"}) == out["entities"]


def test_a_provider_with_no_episode_store_or_no_episode_answer_is_shown_honestly():
    none_yet = summarize(STATS, {"store": {"exists": False}}, "t")
    assert none_yet["episodes"] == {"store_exists": False, "count": None}
    unknown = summarize(STATS, None, "t")
    assert unknown["episodes"] is None  # not "0": the figure simply could not be read


def test_it_asks_synapt_once_a_minute_not_once_a_page_load():
    reader, clock = Reader(), Clock()
    stats = SynaptStats(reader, "p1", ttl=60, clock=clock)
    first = stats.get()
    assert stats.get() == first and reader.calls == ["trident_get_stats", "trident_episodes"]
    clock.now += 59
    assert stats.get() == first and len(reader.calls) == 2
    clock.now += 2
    stats.get()
    assert len(reader.calls) == 4
    stats.get(refresh=True)  # the page's Refresh button
    assert len(reader.calls) == 6


def test_when_synapt_is_unreachable_the_page_gets_a_sentence_not_an_error():
    cold = SynaptStats(Reader(fail={"trident_get_stats"}), "p1").get()
    assert cold == {"available": False, "reason": "Synapt could not be reached just now."}


def test_a_failed_refresh_keeps_the_last_known_figures_and_says_so():
    reader, clock = Reader(), Clock()
    stats = SynaptStats(reader, "p1", ttl=60, clock=clock)
    good = stats.get()
    reader.fail = {"trident_get_stats"}
    clock.now += 120
    stale = stats.get()
    assert stale["available"] is True and stale["stale"] is True and stale["documents"] == good["documents"]
    assert "stale" not in good  # the cached good answer is not mutated


def test_the_episode_count_is_a_nicety_the_rest_still_shows_without_it():
    out = SynaptStats(Reader(fail={"trident_episodes"}), "p1").get()
    assert out["available"] is True and out["documents"] == 38 and out["episodes"] is None


def test_an_adapter_that_cannot_read_gives_a_reason_not_a_crash():
    class NoReads:
        pass

    assert SynaptStats(NoReads(), "p1").get()["available"] is False


def test_the_endpoint_serves_the_figures_and_refresh_goes_back_to_synapt(tmp_path):
    class Adapter(Reader):
        def retrieve(self, claim):  # the application's own read; unused here
            raise AssertionError("not part of this test")

    settings = Settings(
        _env_file=None, synapt_provider_id="p1", claims_database_path=tmp_path / "runtime.sqlite",
        claims_data_path=Path("absent.json"), claims_artifact_dir=tmp_path / "models",
    )
    reader = Adapter()
    app = create_app(settings, adapter=reader)
    with TestClient(app) as client:
        body = client.get("/api/integration/synapt-stats").json()
        assert body["available"] is True and body["documents"] == 38 and body["provider_id"] == "p1"
        client.get("/api/integration/synapt-stats")
        assert len(reader.calls) == 2  # the second request came from the cache
        client.get("/api/integration/synapt-stats?refresh=true")
        assert len(reader.calls) == 4
