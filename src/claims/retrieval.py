import json
import math
import re
from collections import Counter
from pathlib import Path

from claims.demo import fixture_history
from claims.models import ClaimInput, SearchFilters


def tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower())


class HistoricalRetriever:
    """Exact metadata filtering + BM25 + numeric case comparison, explicitly labeled.

    Real semantic evidence retrieval is owned by Synapt. Local lexical/feature scores
    do not claim to be an embedding model or a measured probability.
    """

    def __init__(self, path: Path):
        self.path = path
        self.reload()

    def reload(self):
        self.origin = "synthetic_fixture"
        self.rows = fixture_history()
        if self.path.exists():
            content = json.loads(self.path.read_text(encoding="utf-8"))
            rows = (
                content.get("rows", content.get("data", []))
                if isinstance(content, dict)
                else content
            )
            if rows:
                self.rows = rows
                self.origin = "published_synthetic_dataset"

    def card(self, row):
        return f"{row['claim_type']} {row['state']} policy history {row.get('previous_claims_count', 0)} {row.get('description', '')}"

    def search(self, claim: ClaimInput, filters: SearchFilters, top_k=5, semantic_ids=None):
        candidates = []
        for row in self.rows:
            # Outcomes are only available after a historical claim is closed.
            duration = row.get("days_to_resolution")
            if row.get("claim_status") not in ("approved", "denied") or duration is None:
                continue
            from datetime import date, timedelta

            try:
                closed = date.fromisoformat(str(row["claim_filed_date"])[:10]) + timedelta(
                    days=float(duration)
                )
            except (ValueError, KeyError, TypeError, OverflowError):
                continue
            if closed >= claim.claim_filed_date:
                continue
            if filters.claim_type and row["claim_type"] != filters.claim_type.value:
                continue
            if filters.state and row["state"] != filters.state:
                continue
            if filters.claim_status and row["claim_status"] != filters.claim_status:
                continue
            amount = float(row["claim_amount"])
            history = int(row["previous_claims_count"])
            if not filters.min_amount <= amount <= filters.max_amount:
                continue
            if not filters.min_previous_claims <= history <= filters.max_previous_claims:
                continue
            candidates.append(row)
        if not candidates:
            return []
        docs = [tokens(self.card(row)) for row in candidates]
        query = tokens(f"{claim.description} {claim.claim_type or ''} {claim.state}")
        avg_len = sum(map(len, docs)) / len(docs)
        document_frequency = Counter(term for doc in docs for term in set(doc))
        lexical = []
        for doc in docs:
            score = 0.0
            for term in set(query):
                n = document_frequency[term]
                idf = math.log(1 + (len(docs) - n + 0.5) / (n + 0.5))
                tf = doc.count(term)
                score += idf * (tf * 2.5) / (tf + 1.5 * (0.25 + 0.75 * len(doc) / avg_len))
            lexical.append(score)
        lex_order = sorted(range(len(candidates)), key=lambda i: lexical[i], reverse=True)
        # Feature distance supplements lexical matching; it is not semantic retrieval.
        feature = []
        for row in candidates:
            feature.append(
                (2 if claim.claim_type and row["claim_type"] == claim.claim_type.value else 0)
                + (1 if row["state"] == claim.state else 0)
                + 1
                / (1 + abs(math.log1p(float(row["claim_amount"])) - math.log1p(claim.claim_amount)))
                + 1 / (1 + abs(int(row["previous_claims_count"]) - claim.previous_claims_count))
            )
        feat_order = sorted(range(len(candidates)), key=lambda i: feature[i], reverse=True)
        lex_ranks = {idx: rank for rank, idx in enumerate(lex_order, 1)}
        feat_ranks = {idx: rank for rank, idx in enumerate(feat_order, 1)}
        combined = {
            i: 1 / (60 + lex_ranks[i]) + 1 / (60 + feat_ranks[i]) for i in range(len(candidates))
        }
        semantic_ranks = {claim_id: rank for rank, claim_id in enumerate(semantic_ids or [], 1)}
        for i, row in enumerate(candidates):
            if row["claim_id"] in semantic_ranks:
                combined[i] += 1 / (60 + semantic_ranks[row["claim_id"]])
        result = []
        for i in sorted(combined, key=combined.get, reverse=True)[:top_k]:
            row = candidates[i]
            reasons, differences = [], []
            for field, value in (
                ("claim_type", claim.claim_type.value if claim.claim_type else None),
                ("state", claim.state),
                ("previous_claims_count", claim.previous_claims_count),
            ):
                if row[field] == value:
                    reasons.append(f"Same {field}: {value}")
                else:
                    differences.append(f"{field}: historical {row[field]}, new {value}")
            differences.append(
                f"Claimed amount: historical ${float(row['claim_amount']):,.2f}, new ${claim.claim_amount:,.2f}"
            )
            differences.append(
                "Historical outcome does not establish coverage or fraud for this claim."
            )
            result.append(
                {
                    k: row.get(k)
                    for k in (
                        "claim_id",
                        "claim_type",
                        "state",
                        "claim_amount",
                        "claim_status",
                        "days_to_resolution",
                    )
                }
                | {
                    "similarity_score": round(combined[i], 6),
                    "score_kind": "reciprocal_rank_not_probability",
                    "semantic_match": row["claim_id"] in semantic_ranks,
                    "match_reasons": reasons,
                    "differences": differences,
                    "provenance": self.origin,
                }
            )
        return result
