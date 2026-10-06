import hashlib
import json
import runpy
from datetime import date
from pathlib import Path

import pytest

prepare = runpy.run_path(str(Path(__file__).parents[1] / "scripts" / "prepare_synapt_pack.py"))[
    "prepare"
]


def sample(tmp_path):
    rows = [
        {
            "claim_id": f"CLM-{i}",
            "claim_status": "approved",
            "claim_filed_date": "2025-01-01",
            "days_to_resolution": 10,
            "is_fraud_flagged_ground_truth": True,
        }
        for i in range(15)
    ]
    rows.append(rows[0] | {"claim_id": "CLM-future", "claim_filed_date": "2026-01-01"})
    digest = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"rows": rows, "metadata": {"rows_sha256": digest}}))
    return source


def test_pilot_pack_is_bounded_temporal_and_excludes_fraud_labels(tmp_path):
    source, output = sample(tmp_path), tmp_path / "claims.md"
    result = prepare(source, output, date(2026, 1, 1), limit=10, offset=2)
    text = output.read_text()
    assert result["cards"] == 10 and result["synapt_uploaded"] is False
    assert "## Claim CLM-2\n" in text and "## Claim CLM-0\n" not in text
    assert "CLM-future" not in text and "is_fraud_flagged_ground_truth" not in text


def test_pack_rejects_modified_source_rows(tmp_path):
    source = sample(tmp_path)
    payload = json.loads(source.read_text())
    payload["rows"][0]["claim_id"] = "changed"
    source.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="SHA256"):
        prepare(source, tmp_path / "claims.md", date(2026, 1, 1))
