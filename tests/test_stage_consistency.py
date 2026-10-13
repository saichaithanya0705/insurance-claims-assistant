"""The workflow, the explanation page, the observability page and the UI must name the same stages."""

import re
from pathlib import Path

from claims.api.main import create_app
from claims.core.settings import Settings
from claims.observability.explain import STAGES as EXPLAIN_STAGES
from claims.observability.observatory import STAGE_ORDER

ROOT = Path(__file__).resolve().parents[1]


def ui_stage_keys():
    source = (ROOT / "frontend/src/components/Pipeline.tsx").read_text(encoding="utf-8")
    return re.findall(r"\{ key: '(\w+)', name:", source)


def test_every_surface_lists_the_workflow_stages_in_the_same_order(tmp_path):
    settings = Settings(_env_file=None, claims_database_path=tmp_path / "s.sqlite",
                        claims_data_path=tmp_path / "missing.json", claims_artifact_dir=tmp_path / "models")
    service = create_app(settings).state.service
    workflow = {name for name in service.graph.get_graph().nodes if not name.startswith("__")}
    explain = [key for key, _ in EXPLAIN_STAGES]
    observed = sorted(STAGE_ORDER, key=STAGE_ORDER.get)
    ui = ui_stage_keys()
    assert workflow == set(explain), "the workflow graph and the explanation page disagree"
    assert explain == observed == ui, "stage order differs between explanation, observability and the UI"
    assert len(explain) == 9
    service.close()


def test_the_connection_page_does_not_hard_code_a_stage_count():
    connection = (ROOT / "frontend/src/components/ConnectionView.tsx").read_text(encoding="utf-8")
    assert not re.search(r"\d-stage workflow", connection)
    assert "STAGES.length" in connection
