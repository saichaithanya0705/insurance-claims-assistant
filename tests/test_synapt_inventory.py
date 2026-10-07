"""Graph-based verification of the Synapt store (offline: a fake provider stands in for the tenant)."""

import asyncio
import json

from claims.synapt_inventory import (
    build_expected,
    marker_pattern,
    summary_lines,
    verify_store,
)

MARKERS = ["cardpack_aaaa1111bbbb2222cccc", "cardpack_f22102cd4f511272094a", "cardpack_dddd3333eeee4444ffff"]
WRAPPER = 1_094


def expected():
    return {
        "base": {"batches": [{"name": f"cards-{i:04d}.txt", "cards": 100, "chars": 30_000 + i * 17}
                              for i in range(1, 4)]},
        "expansion": {"batches": [
            {"name": "expanded-0001.txt", "cards": 500, "chars": 150_000, "marker": MARKERS[0]},
            {"name": "expanded-0002.txt", "cards": 500, "chars": 151_000, "marker": MARKERS[1]},
            {"name": "expanded-0003.txt", "cards": 387, "chars": 116_000, "marker": MARKERS[2]},
        ]},
        "procedures": ["SOP-AUTO-001", "SOP-REVIEW-001"],
    }


class FakeSynapt:
    """Serves what trident_get_stats, trident_cypher and trident_get_chunks return for a provider."""

    def __init__(self, spec=None, masked=True, procedures=("SOP-AUTO-001", "SOP-REVIEW-001"), header_hits=True):
        spec = spec or expected()
        self.docs, self.headers = {}, []
        for i, batch in enumerate(spec["base"]["batches"]):
            self.docs[f"base-{i}.txt"] = {"f": f"base-{i}.txt", "n": batch["cards"],
                                          "linked": batch["cards"], "lo": 0, "hi": batch["chars"] + 294}
        for i, batch in enumerate(spec["expansion"]["batches"]):
            name = f"exp-{i}.txt"
            wrapper = WRAPPER if batch["cards"] == 500 else 868
            self.docs[name] = {"f": name, "n": batch["cards"], "linked": batch["cards"], "lo": 0,
                               "hi": batch["chars"] + wrapper}
            marker = batch["marker"]
            if masked and "511272094" in marker:
                marker = marker.replace("511272094", "[US_SSN_6a56812069f5]")
            self.headers.append({"source_file": name, "text": f"# {name}\n\n## Page 1\n\n### Historical "
                                 f"claim cards; corpus batch {marker}\n\nSource: ..."})
        self.procedures, self.header_hits, self.calls = set(procedures), header_hits, []

    async def call_read_tool(self, name, arguments, max_response_chars=None):
        self.calls.append(name)
        assert name in {"trident_get_stats", "trident_cypher", "trident_get_chunks"}, "read-only tools only"
        if name == "trident_get_stats":
            return {"result": json.dumps({"doc_count": len(self.docs) + 2, "chunks": 1_234})}
        if name == "trident_cypher":
            return {"result": json.dumps(sorted(self.docs.values(), key=lambda d: d["hi"]))}
        query = arguments["query"]
        if query.startswith("Historical claim cards"):
            return {"result": json.dumps(self.headers if self.header_hits else [])}
        if query.startswith("corpus batch"):
            return {"result": json.dumps([])}
        hits = [{"source_file": "sop.txt", "text": f"procedure source_id: {sid}"}
                for sid in self.procedures if sid in query]
        return {"result": json.dumps({"chunks": hits})}


def run(fake, spec=None):
    return asyncio.run(verify_store(fake, "provider", spec or expected()))


def test_complete_store_is_verified_and_read_only():
    fake = FakeSynapt()
    report = run(fake)
    assert report["ok"] and report["expansion"]["state"] == "complete"
    assert report["base"]["verified"] == 3 and report["expansion"]["verified"] == 3
    assert report["stats"]["documents_matched_to_batches"] == 6 and all(report["procedures"].values())
    assert set(fake.calls) <= {"trident_get_stats", "trident_cypher", "trident_get_chunks"}
    assert all(mark in {"ok", ".."} for mark, _ in summary_lines(report))


def test_masked_marker_is_still_identified():
    unmasked, masked = run(FakeSynapt(masked=False)), run(FakeSynapt(masked=True))
    assert masked["expansion"]["verified"] == unmasked["expansion"]["verified"] == 3


def test_marker_pattern_only_forgives_long_digit_runs():
    pattern = marker_pattern("cardpack_f22102cd4f511272094a")
    assert pattern.search("batch cardpack_f22102cd4f[US_SSN_6a56812069f5]a")
    assert pattern.search("batch cardpack_f22102cd4f511272094a")
    assert not pattern.search("batch cardpack_f22102cd4f[US_SSN_6a56812069f5]b")
    assert not marker_pattern("cardpack_ab12cd").search("cardpack_ab[US_SSN_1]cd")


def test_document_one_card_short_fails():
    fake = FakeSynapt()
    fake.docs["exp-1.txt"].update(n=499, linked=499, hi=fake.docs["exp-1.txt"]["hi"] - 330)
    report = run(fake)
    assert not report["ok"] and report["expansion"]["state"] == "incomplete"
    assert report["expansion"]["batches"][1]["status"] == "failed"
    assert any("499 chunks for 500 cards" in line for _, line in summary_lines(report))


def test_one_extra_chunk_is_accepted():
    fake = FakeSynapt()
    fake.docs["exp-0.txt"].update(n=501, linked=501)
    assert run(fake)["ok"]


def test_chunk_nodes_must_be_linked():
    fake = FakeSynapt()
    fake.docs["base-0.txt"]["linked"] = 90
    report = run(fake)
    assert not report["ok"] and report["base"]["verified"] == 2


def test_truncated_text_with_correct_chunk_count_fails():
    fake = FakeSynapt()
    fake.docs["exp-0.txt"]["hi"] -= 330  # same chunk count, shorter text: a card was cut inside a chunk
    report = run(fake)
    assert report["expansion"]["batches"][0]["status"] == "failed"


def test_absent_expansion_is_optional():
    fake = FakeSynapt(header_hits=False)
    for name in [n for n in fake.docs if n.startswith("exp-")]:
        del fake.docs[name]
    report = run(fake)
    assert report["expansion"]["state"] == "absent" and report["ok"]
    assert ("..", "expansion corpus: not ingested (optional; the app needs only the base cards)") in summary_lines(report)


def test_absent_expansion_does_not_hide_base_problems():
    fake = FakeSynapt(header_hits=False)
    for name in [n for n in fake.docs if n.startswith("exp-")]:
        del fake.docs[name]
    fake.docs["base-1.txt"]["linked"] = 5
    report = run(fake)
    assert not report["ok"]
    assert any(mark == "XX" and "cards-0002.txt" in text for mark, text in summary_lines(report))


def test_expansion_with_unidentified_batches_is_incomplete_not_absent():
    fake = FakeSynapt()
    fake.headers = fake.headers[:2]  # one batch header cannot be found
    report = run(fake)
    assert report["expansion"]["state"] == "incomplete" and not report["ok"]
    assert report["expansion"]["batches"][2]["status"] == "unidentified"


def test_base_batches_that_cannot_be_paired_are_unidentified():
    fake = FakeSynapt()
    del fake.docs["base-2.txt"]
    report = run(fake)
    assert not report["ok"] and report["base"]["verified"] == 0
    assert all(b["status"] == "unidentified" for b in report["base"]["batches"])


def test_missing_procedure_fails_readiness():
    report = run(FakeSynapt(procedures=("SOP-AUTO-001",)))
    assert not report["ok"] and report["procedures"] == {"SOP-AUTO-001": True, "SOP-REVIEW-001": False}
    assert ("XX", "procedure SOP-REVIEW-001 not found") in summary_lines(report)


def test_build_expected_describes_local_corpora(tmp_path):
    def corpus(name, batches, marker):
        root = tmp_path / name
        (root / "cards").mkdir(parents=True)
        entries = []
        for i, cards in enumerate(batches, 1):
            path = f"cards/{name}-{i:04d}.txt"
            (root / path).write_text("x" * (100 * cards), encoding="utf-8")
            entry = {"path": path, "sha256": f"sha{i}", "claim_ids": [f"CLM-{n:010d}" for n in range(cards)]}
            if marker:
                entry |= {"marker": f"cardpack_{i:020d}", "cards": cards}
            entries.append(entry)
        (root / "manifest.json").write_text(json.dumps({"batches": entries}), encoding="utf-8")
        return root

    base, expansion = corpus("base", [3, 3], False), corpus("exp", [5], True)
    (base / "procedures").mkdir()
    (base / "procedures" / "sop-a.txt").write_text("# Title\nsource_id: SOP-A-001\n", encoding="utf-8")
    result = build_expected(base, expansion)
    assert result["base"]["batches"][0] == {"name": "base-0001.txt", "cards": 3, "chars": 300, "sha256": "sha1"}
    assert result["expansion"]["batches"][0]["marker"] == "cardpack_00000000000000000001"
    assert result["expansion"]["batches"][0]["chars"] == 500 and result["procedures"] == ["SOP-A-001"]
