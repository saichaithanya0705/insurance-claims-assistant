"""Measure what Synapt's ticket store predicts for settled claims it has never seen.

    python scripts/ticket_label_trial.py --provider ticketing_sample --output artifacts/synapt/ticketing-sample/label-trial.json

The provider is the one built from `scripts/make_ticketing_sample.py` (300 settled claims). The trial draws 100 other
settled claims (20 per claim type, 4 of them flagged, none in the workbook), sends only the embedded columns (title,
description, category, region) with `ticket_mode="only"`, and compares the predicted `resolution` and `fraud_flag` with
the dataset's values. `only` runs no language model and writes no episode, so the call is read-only. Reported: accuracy
against the majority-class baseline, per-class recall, and AUC of the minority-class confidence (does the confidence rank
the true minority claims higher even when the top label is the majority?). The held-out fraud rate is 20 %, not the
dataset's 7.6 %, so accuracy is compared with that sample's own majority baseline.
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import make_ticketing_sample as sample

from claims.core.settings import Settings
from claims.corpus.builder import CLAIM_TYPES
from claims.history.dataset import ClaimsStore
from claims.synapt.adapter import LiveSynaptAdapter

FIELDS = ("resolution", "fraud_flag")
MINORITY = {"resolution": "denied", "fraud_flag": "flagged"}
BATCH = 25  # the tool accepts at most 50 tickets per call


def held_out(store: ClaimsStore, seed: int, workbook_seed: int = 2026, per_type: int = 60, flagged: int | None = 12) -> list[dict]:
    """20 settled claims per type (4 flagged) that are not among the workbook's tickets (``per_type`` and ``flagged`` as it was built)."""
    in_store = {r["claim_id"] for r in sample.sample_rows(store, per_type, flagged, workbook_seed)}
    pool = [r for r in sample.sample_rows(store, 40, 10, seed) if r["claim_id"] not in in_store]
    chosen: list[dict] = []
    for kind in CLAIM_TYPES:
        of_kind = [r for r in pool if r["claim_type"] == kind]
        chosen += [r for r in of_kind if r["is_fraud_flagged_ground_truth"]][:4]
        chosen += [r for r in of_kind if not r["is_fraud_flagged_ground_truth"]][:16]
    return chosen


def auc(positive: list[float], negative: list[float]) -> float:
    wins = sum((p > n) + 0.5 * (p == n) for p in positive for n in negative)
    return wins / (len(positive) * len(negative))


async def label(adapter: LiveSynaptAdapter, provider: str, tickets: list[dict]) -> list[dict]:
    items: list[dict] = []
    async with adapter._session() as session:
        for start in range(0, len(tickets), BATCH):
            for attempt in range(3):
                result = await session.call_tool("trident_query", arguments={
                    "provider_id": provider, "question": "Which labels do the most similar settled claims carry?",
                    "ticket_mode": "only", "tickets": tickets[start:start + BATCH], "label_fields": list(FIELDS),
                })
                text = "".join(b.text for b in result.content if b.type == "text")
                if not result.isError and "ticket_labels" in text:
                    break
                print(f"batch {start}: attempt {attempt + 1} failed: {text[:300]}")
            else:
                raise SystemExit("Synapt failed three times for one batch; nothing was measured")
            items += json.loads(text)["ticket_labels"]
    return items


def confidence(item: dict, field: str, value: str) -> float:
    return next((x["confidence"] for x in item["fields"][field]["labels"] if x["value"] == value), 0.0)


def report(truth: list[dict], items: list[dict]) -> dict:
    out: dict = {"claims": len(truth), "neighbours_per_ticket": sorted({i["assignment"]["neighbours_used"] for i in items})}
    for field in FIELDS:
        actual = [t[field] for t in truth]
        top = [max(i["fields"][field]["labels"], key=lambda x: x["confidence"])["value"] for i in items]
        majority, count = Counter(actual).most_common(1)[0]
        minority = MINORITY[field]
        scores = [confidence(i, field, minority) for i in items]
        positive = [s for s, a in zip(scores, actual) if a == minority]
        negative = [s for s, a in zip(scores, actual) if a != minority]
        out[field] = {
            "truth": dict(Counter(actual)), "majority_baseline": round(count / len(actual), 3), "majority_label": majority,
            "synapt_top_label_accuracy": round(sum(a == p for a, p in zip(actual, top)) / len(actual), 3),
            "predicted_counts": dict(Counter(top)),
            f"recall_{minority}": f"{sum(a == p == minority for a, p in zip(actual, top))}/{len(positive)}",
            f"auc_{minority}_confidence": round(auc(positive, negative), 3),
            f"mean_{minority}_confidence_true_vs_other": [round(sum(positive) / len(positive), 3), round(sum(negative) / len(negative), 3)],
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--provider", required=True, help="ticket provider id, e.g. ticketing_sample")
    parser.add_argument("--seed", type=int, default=777)
    parser.add_argument("--workbook-per-type", type=int, default=60, help="tickets per claim type in the uploaded workbook")
    parser.add_argument("--workbook-natural", action="store_true", help="the workbook was built with --natural")
    parser.add_argument("--workbook-seed", type=int, default=2026)
    parser.add_argument("--output", type=Path, help="write the truth, raw Synapt labels and summary here")
    args = parser.parse_args()
    store = ClaimsStore(Settings().claims_parquet_path, memory_limit="3GB")
    try:
        rows = held_out(store, args.seed, args.workbook_seed, args.workbook_per_type, None if args.workbook_natural else 12)
    finally:
        store.close()
    table = [sample.ticket(r) for r in rows]
    tickets = [{"title": t[1], "description": t[2], "category": t[3], "region": t[4]} for t in table]
    truth = [{"ticket_id": t[0], "type": t[3], "resolution": t[11], "fraud_flag": t[13]} for t in table]
    items = asyncio.run(label(LiveSynaptAdapter(Settings()), args.provider, tickets))
    if len(items) != len(truth):
        raise SystemExit(f"Synapt returned {len(items)} labels for {len(truth)} tickets")
    summary = report(truth, items)
    print(json.dumps(summary, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"summary": summary, "truth": truth, "ticket_labels": items}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
