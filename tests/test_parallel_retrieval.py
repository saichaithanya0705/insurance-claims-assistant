"""The retrieve stage runs its slow, independent parts together, and the result does not depend on who finishes first.

A live run took 16 s in retrieval because the passage search, the graph lookup, the past-claim search and the DuckDB cohort scan
ran one after another (2.3 + 4.0 + 3.9 + 5.0 s). The scan needs only the claim, so it now starts at once; the graph lookup and the
query agent start as soon as the passages are in; the past-claim search runs beside them. These tests prove the overlap with
events rather than clocks (a clock test is a flaky test), and that the evidence still comes back in its fixed order.
"""

import threading
import time

import pytest
from fastapi.testclient import TestClient
from test_cohort import LocalCopy, SynaptDown, SynaptUp, build_source, workflow_claim
from test_sidechat import QUERY

from claims.api.main import create_app
from claims.core.schemas import ClaimInput, SearchFilters
from claims.core.settings import Settings
from claims.history import cohort
from claims.synapt import knowledge_graph
from claims.synapt.adapter import SynaptError

RUN = "11111111-1111-4111-8111-111111111111"
WAIT = 10  # seconds a worker may wait for another before the test calls the overlap absent


class Overlapping(SynaptUp):
    """A live adapter whose slow calls each wait for the DuckDB scan to be running, as they would if they overlapped it."""

    def __init__(self, card_ids, scan_started):
        super().__init__(card_ids)
        self.scan_started, self.saw_scan = scan_started, {}

    def retrieve(self, claim):
        self.saw_scan["passages"] = self.scan_started.wait(WAIT)
        return super().retrieve(claim)

    def retrieve_graph(self, claim):
        self.saw_scan["graph"] = self.scan_started.wait(WAIT)
        return knowledge_graph.unavailable("not needed here")


@pytest.fixture
def retrieval_settings(tmp_path):
    source_path = tmp_path / "source.parquet"
    build_source(source_path)
    return Settings(
        _env_file=None,
        claims_database_path=tmp_path / "runtime.sqlite",
        claims_data_path=tmp_path / "absent.json",
        claims_artifact_dir=tmp_path / "models",
        claims_parquet_path=source_path,
    )


@pytest.fixture
def scan_started(monkeypatch):
    started = threading.Event()
    original = cohort._aggregate

    def spy(store, cell, cutoff):
        started.set()
        return original(store, cell, cutoff)

    monkeypatch.setattr(cohort, "_aggregate", spy)
    return started


def card_ids(retrieval_settings):
    source = build_source(retrieval_settings.claims_parquet_path.parent / "ids.parquet")
    return source["exact"][:2]


def test_the_cohort_scan_starts_before_the_passage_search_ends_and_the_graph_lookup_runs_while_it_is_busy(retrieval_settings, scan_started):
    adapter = Overlapping([], scan_started)
    app = create_app(retrieval_settings, adapter=adapter)
    with TestClient(app):
        context = app.state.service.retrieve_context(ClaimInput.model_validate(workflow_claim()), SearchFilters())
    # Had the stage run in the old order, the passage search would have waited for a scan that had not started, and said so.
    assert adapter.saw_scan == {"passages": True, "graph": True}
    assert context["cohort"]["available"] is True and [c["claims"] for c in context["cohort"]["cohorts"]] == [30, 60, 65]


def test_the_evidence_comes_back_in_its_fixed_order_whichever_part_finishes_first(retrieval_settings):
    class SlowGraph(SynaptUp):
        def retrieve_graph(self, claim):
            time.sleep(0.4)  # the slowest part: it must still land between the passages and the submitted claim
            return knowledge_graph.unavailable("slow")

    app = create_app(retrieval_settings, adapter=SlowGraph([]))
    with TestClient(app):
        context = app.state.service.retrieve_context(ClaimInput.model_validate(workflow_claim()), SearchFilters())
    ids = [e["source_id"] for e in context["evidence"]]
    assert ids[0] == "procedure:auto" and ids[1] == "claim:input"
    assert all(i.startswith("history:") for i in ids[2:]) and len(ids) > 2


def test_a_failed_graph_lookup_is_reported_and_does_not_stop_the_rest(retrieval_settings):
    class BrokenGraph(SynaptUp):
        def retrieve_graph(self, claim):
            raise SynaptError("graph down")

    app = create_app(retrieval_settings, adapter=BrokenGraph([]))
    with TestClient(app):
        context = app.state.service.retrieve_context(ClaimInput.model_validate(workflow_claim()), SearchFilters())
    assert context["graph"]["available"] is False
    assert any("knowledge-graph lookup failed" in w for w in context["warnings"])
    assert context["cohort"]["available"] is True and context["similar_cases"]


def test_when_retrieval_fails_the_error_comes_back_promptly_and_the_waiting_scan_is_released(retrieval_settings):
    class Down:
        def retrieve(self, claim):
            raise SynaptError("Synapt is unreachable")

    app = create_app(retrieval_settings, adapter=Down(), fallback=None)
    started = time.perf_counter()
    with TestClient(app), pytest.raises(SynaptError):
        app.state.service.retrieve_context(ClaimInput.model_validate(workflow_claim()), SearchFilters())
    # the scan had nothing to wait for and must not hold the failure for its 120 s semantic-match timeout
    assert time.perf_counter() - started < 30
    assert threading.active_count() < 20  # and nothing is left running behind it


def test_the_cohort_still_cross_checks_the_cards_retrieval_returned_even_though_the_scan_started_first(retrieval_settings):
    ids = card_ids(retrieval_settings)
    app = create_app(retrieval_settings, adapter=SynaptUp(ids))
    with TestClient(app):
        context = app.state.service.retrieve_context(ClaimInput.model_validate(workflow_claim()), SearchFilters())
    check = context["cohort"]["synapt_cross_check"]
    assert check is not None and check["cards_returned"] == 2


# ----- the query agent and the graph lookup start with the passage search ------------------------------------------------------


class AllAtOnce(SynaptUp):
    """The passage search will not finish until the query agent and the graph lookup have both been started."""

    def __init__(self, card_ids):
        super().__init__(card_ids)
        self.asked, self.graph_started, self.ready = threading.Event(), threading.Event(), {}

    def ask(self, question, **kwargs):
        self.asked.set()
        return QUERY

    def retrieve_graph(self, claim):
        self.graph_started.set()
        return knowledge_graph.unavailable("not needed here")

    def retrieve(self, claim):
        self.ready["query"] = self.asked.wait(WAIT)
        self.ready["graph"] = self.graph_started.wait(WAIT)
        return super().retrieve(claim)


def test_the_query_agent_and_the_graph_lookup_start_before_the_passage_search_ends(retrieval_settings):
    adapter = AllAtOnce([])
    app = create_app(retrieval_settings, adapter=adapter)
    with TestClient(app):
        context = app.state.service.retrieve_context(ClaimInput.model_validate(workflow_claim()), SearchFilters(), run_id=RUN)
    assert adapter.ready == {"query": True, "graph": True}  # in the old order the passage search waited for both, in vain
    assert context["query_agent"]["available"] is True and context["graph"]["available"] is False


def test_a_run_that_fell_back_to_the_local_copy_ignores_the_graph_and_the_answer_that_were_asked_for_before_it_was_known(retrieval_settings):
    class DownWithExtras(SynaptDown):
        def ask(self, question, **kwargs):
            return QUERY

        def retrieve_graph(self, claim):
            return knowledge_graph.unavailable("asked for before the outage was known")

    app = create_app(retrieval_settings, adapter=DownWithExtras(), fallback=LocalCopy([]))
    with TestClient(app):
        context = app.state.service.retrieve_context(ClaimInput.model_validate(workflow_claim()), SearchFilters(), run_id=RUN)
    assert context["mode"] == "degraded" and context["graph"] is None and context["query_agent"] is None


def test_with_no_wait_the_brief_gets_a_pending_answer_at_once_and_settling_picks_the_answer_up_when_it_is_ready(retrieval_settings):
    release = threading.Event()

    class Slow(AllAtOnce):
        def ask(self, question, **kwargs):
            release.wait(WAIT)
            return QUERY

        def retrieve(self, claim):
            return SynaptUp.retrieve(self, claim)

    app = create_app(retrieval_settings, adapter=Slow([]))
    with TestClient(app):
        service = app.state.service
        context = service.retrieve_context(ClaimInput.model_validate(workflow_claim()), SearchFilters(), run_id=RUN, query_wait=0)
        assert context["query_agent"]["pending"] is True and RUN in service.pending_queries
        release.set()
        settled = service.settle_query_answer(RUN, {"query_agent": context["query_agent"], "findings": []})
    assert settled["query_agent"]["available"] is True and RUN not in service.pending_queries


def test_settling_reports_a_failed_answer_as_a_limitation_and_leaves_a_slow_one_pending(retrieval_settings, monkeypatch):
    from concurrent.futures import Future

    from claims.investigation import workflow
    from claims.synapt import query_agent

    app = create_app(retrieval_settings, adapter=SynaptUp([]))
    with TestClient(app):
        service = app.state.service
        pending = {"query_agent": query_agent.pending("Q?", RUN), "findings": [{"kind": "fact", "text": "x", "source_ids": ["claim:input"]}]}
        failed = Future()
        failed.set_exception(RuntimeError("socket closed; token abc123"))
        service.pending_queries[RUN] = failed
        out = service.settle_query_answer(RUN, pending)
        assert out["query_agent"]["available"] is False and "abc123" not in str(out)
        assert out["findings"][-1]["kind"] == "limitation" and "did not answer" in out["findings"][-1]["text"]
        monkeypatch.setattr(workflow, "QUERY_GRACE_SECONDS", 0.1)
        service.pending_queries[RUN] = Future()  # never completes
        assert service.settle_query_answer(RUN, pending)["query_agent"]["pending"] is True


def test_the_numeric_pool_is_fetched_before_the_passage_search_ends_and_the_semantic_matches_are_added_after(retrieval_settings):
    ids = card_ids(retrieval_settings)
    seen = {}

    class Slow(SynaptUp):
        def retrieve(self, claim):
            seen["pool_started_before_passages_ended"] = pool_started.wait(WAIT)
            return super().retrieve(claim)

    pool_started = threading.Event()
    app = create_app(retrieval_settings, adapter=Slow(ids))
    with TestClient(app):
        service = app.state.service
        original = service.retriever.prefetch

        def spy(claim, filters):
            pool_started.set()
            return original(claim, filters)

        service.retriever.prefetch = spy
        context = service.retrieve_context(ClaimInput.model_validate(workflow_claim()), SearchFilters())
    assert seen == {"pool_started_before_passages_ended": True}
    assert context["similar_cases"] and context["semantic"]["semantic_candidates"] == len(ids)


def test_search_with_a_prefetched_pool_returns_exactly_what_it_returns_without_one(retrieval_settings):
    app = create_app(retrieval_settings, adapter=SynaptUp([]))
    with TestClient(app):
        retriever = app.state.service.retriever
        claim = ClaimInput.model_validate(workflow_claim())
        plain = retriever.search(claim, SearchFilters(), 5, [])
        with_pool = retriever.search(claim, SearchFilters(), 5, [], pool=retriever.prefetch(claim, SearchFilters()))
    assert [c["claim_id"] for c in plain] == [c["claim_id"] for c in with_pool] and plain == with_pool
