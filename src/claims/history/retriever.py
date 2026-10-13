import json
import math
import re
import threading
from datetime import date, timedelta
from pathlib import Path

from claims.core.demo_cases import fixture_history
from claims.core.schemas import ClaimInput, SearchFilters
from claims.corpus.cards import claim_card_text
from claims.history.dataset import CLOSED_STATUSES, OPEN_STATUSES, ClaimsStore

SEMANTIC_WEIGHT = 0.5
RRF_K = 60


def tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower())


class HistoricalRetriever:
    """Exact metadata filtering, keyword (BM25) ranking, numeric similarity and semantic ranks.

    History comes from the full Parquet dataset through DuckDB when it is present, otherwise from
    a bounded JSON sample or the built-in fixtures. Semantic ranks arrive from Synapt as claim IDs
    (``semantic_ids``); the local scores do not claim to be an embedding model or a probability.
    """

    def __init__(
        self,
        path: Path,
        parquet_path: Path | None = None,
        *,
        candidate_limit: int = 300,
        memory_limit: str = "3GB",
        copy_path: Path | None = None,
    ):
        self.path = path
        self.parquet_path = Path(parquet_path) if parquet_path else None
        self.candidate_limit = candidate_limit
        self.memory_limit = memory_limit
        self.copy_path = Path(copy_path) if copy_path else None
        self.store: ClaimsStore | None = None
        # What Synapt's semantic list contributed to the most recent search (for the trace).
        self.last_search: dict = {"semantic_candidates": 0, "semantic_eligible": 0, "semantic_in_results": 0}
        # How the most recent search ranked its results (for the trace); kept apart from
        # ``last_search`` and from the case dictionaries, which models read as evidence text.
        self.last_trace: dict = {}
        self.reload()

    def reload(self):
        self.origin = "synthetic_fixture"
        self.rows = fixture_history()
        if self.parquet_path and self.parquet_path.is_file():
            if self.store is None:
                self.store = ClaimsStore(self.parquet_path, memory_limit=self.memory_limit)
                if self.store.attach_copy(self.copy_path):
                    threading.Thread(target=self.store.warm_copy, name="warm-copy", daemon=True).start()
            self.rows = []
            self.origin = "published_synthetic_dataset"
            return
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

    def close(self):
        if self.store is not None:
            self.store.close()
            self.store = None

    def card(self, row):
        return f"{claim_card_text(row, include_outcome=False)} {row.get('description', '')}"

    def _json_candidates(self, claim: ClaimInput, filters: SearchFilters):
        candidates = []
        status_filter = filters.claim_status
        for row in self.rows:
            status = row.get("claim_status")
            duration = row.get("days_to_resolution")
            if status_filter in OPEN_STATUSES:
                # Open claims have no outcome; they only need to have been on file already.
                if status != status_filter:
                    continue
                try:
                    if date.fromisoformat(str(row["claim_filed_date"])[:10]) >= claim.claim_filed_date:
                        continue
                except (ValueError, KeyError, TypeError):
                    continue
            else:
                # Outcomes are only available after a historical claim is closed.
                if status not in CLOSED_STATUSES or duration is None:
                    continue
                if status_filter and status != status_filter:
                    continue
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
            # Like the Parquet search: with no type chosen, compare the claim's own type, never every type.
            if not filters.claim_type and claim.claim_type and row["claim_type"] != claim.claim_type.value:
                continue
            if filters.state and row["state"] != filters.state:
                continue
            amount = float(row["claim_amount"])
            history = int(row["previous_claims_count"])
            if not filters.min_amount <= amount <= filters.max_amount:
                continue
            if not filters.min_previous_claims <= history <= filters.max_previous_claims:
                continue
            candidates.append(row)
        return candidates

    def prefetch(self, claim, filters):
        """The numeric part of the candidate pool (the 300 closest by feature score). It depends only on the claim and the filters,
        so it can be fetched while Synapt is still being asked; ``search`` then adds the semantic matches. None with no Parquet."""
        if self.store is None:
            return None
        return self.store.candidates(claim, filters, limit=self.candidate_limit)

    def _candidates(self, claim, filters, semantic_ids, pool=None):
        if self.store is None:
            rows = self._json_candidates(claim, filters)
            self.last_search["semantic_eligible"] = sum(
                row["claim_id"] in set(semantic_ids or []) for row in rows
            )
            self.last_trace["sql_candidates"] = len(rows)
            return rows
        rows = list(pool) if pool is not None else self.store.candidates(claim, filters, limit=self.candidate_limit)
        self.last_trace["sql_candidates"] = len(rows)
        if semantic_ids:
            seen = {row["claim_id"] for row in rows}
            eligible = self.store.candidates(claim, filters, ids=list(semantic_ids)[:100])
            self.last_search["semantic_eligible"] = len(eligible)
            added = [row for row in eligible if row["claim_id"] not in seen]
            rows += added
            self.last_trace["semantic_added"] = len(added)
        return rows

    def search(
        self,
        claim: ClaimInput,
        filters: SearchFilters,
        top_k=5,
        semantic_ids=None,
        semantic_extra=3,
        pool=None,
    ):
        """Closest historical claims (``top_k``), then up to ``semantic_extra`` more that Synapt
        ranks as related in meaning but that the numeric search would not have surfaced."""
        self.last_search = {
            "semantic_candidates": len(semantic_ids or []),
            "semantic_eligible": 0,
            "semantic_in_results": 0,
        }
        self.last_trace = {
            "source": "parquet" if self.store is not None else "sample",
            "origin": self.origin,
            "top_k": top_k,
            "rrf_k": RRF_K,
            "weights": {"keyword": 1.0, "feature": 1.0, "semantic": SEMANTIC_WEIGHT},
            "sql_candidates": 0,
            "semantic_added": 0,
            "pool_size": 0,
            "ranked": [],
        }
        candidates = self._candidates(claim, filters, semantic_ids, pool)
        self.last_trace["pool_size"] = len(candidates)
        if not candidates:
            return []
        docs = [tokens(self.card(row)) for row in candidates]
        query = tokens(
            f"{claim.description} {claim_card_text(claim.model_dump(), include_outcome=False)}"
        )
        avg_len = sum(map(len, docs)) / len(docs)
        # Keyword leg: term-frequency match over claim descriptors. There is deliberately no IDF
        # weighting: every descriptor (type, state, bands, history) is equally informative, and
        # the pool is ~300 near-identical claims plus a few diverse semantic outliers, so IDF would
        # reward the outliers' rare terms and rank them above the genuinely closest claims.
        lexical = []
        for doc in docs:
            score = 0.0
            for term in set(query):
                tf = doc.count(term)
                score += (tf * 2.5) / (tf + 1.5 * (0.25 + 0.75 * len(doc) / avg_len))
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
            i: 1 / (RRF_K + lex_ranks[i]) + 1 / (RRF_K + feat_ranks[i])
            for i in range(len(candidates))
        }
        semantic_ranks = {claim_id: rank for rank, claim_id in enumerate(semantic_ids or [], 1)}
        # Weighted fusion: Synapt holds only a sample of the history, so its nearest cards can be
        # poor numeric matches. Its rank may lift or break ties among good candidates but, at half
        # weight, cannot displace claims that rank high on both keyword and feature similarity.
        for i, row in enumerate(candidates):
            if row["claim_id"] in semantic_ranks:
                combined[i] += SEMANTIC_WEIGHT / (RRF_K + semantic_ranks[row["claim_id"]])
        chosen = sorted(combined, key=combined.get, reverse=True)[:top_k]
        extras = []
        if semantic_ranks and semantic_extra:
            by_id = {row["claim_id"]: i for i, row in enumerate(candidates)}
            extras = [
                by_id[claim_id]
                for claim_id in sorted(semantic_ranks, key=semantic_ranks.get)
                if claim_id in by_id and by_id[claim_id] not in chosen
            ][:semantic_extra]
        result = []
        for i, surfaced_by in [(i, "fusion") for i in chosen] + [(i, "semantic") for i in extras]:
            case = self._case(claim, candidates[i], combined[i], semantic_ranks, surfaced_by)
            self.last_search["semantic_in_results"] += case["semantic_match"]
            result.append(case)
            semantic_rank = semantic_ranks.get(candidates[i]["claim_id"])
            self.last_trace["ranked"].append(
                {
                    "claim_id": candidates[i]["claim_id"],
                    "surfaced_by": surfaced_by,
                    "keyword_rank": lex_ranks[i],
                    "feature_rank": feat_ranks[i],
                    "semantic_rank": semantic_rank,
                    "keyword_score": round(lexical[i], 4),
                    "feature_score": round(feature[i], 4),
                    "keyword_points": round(1 / (RRF_K + lex_ranks[i]), 6),
                    "feature_points": round(1 / (RRF_K + feat_ranks[i]), 6),
                    "semantic_points": round(SEMANTIC_WEIGHT / (RRF_K + semantic_rank), 6)
                    if semantic_rank
                    else 0.0,
                    "total": round(combined[i], 6),
                }
            )
        return result

    def _case(self, claim, row, score, semantic_ranks, surfaced_by):
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
        differences.append("Historical outcome does not establish coverage or fraud for this claim.")
        if surfaced_by == "semantic":
            reasons.append(
                f"Related in meaning: Synapt's ticket store ranked this past claim #{semantic_ranks[row['claim_id']]}"
            )
        return {
            k: row.get(k)
            for k in (
                "claim_id",
                "claim_type",
                "state",
                "claim_amount",
                "deductible",
                "previous_claims_count",
                "policyholder_tenure_years",
                "claim_status",
                "days_to_resolution",
            )
        } | {
            # Dataset label, not proof of fraud; None when the source has no such field.
            "dataset_fraud_flag": row.get("is_fraud_flagged_ground_truth"),
            "open_case": row.get("claim_status") in OPEN_STATUSES,
            "similarity_score": round(score, 6),
            "score_kind": "reciprocal_rank_not_probability",
            "semantic_match": row["claim_id"] in semantic_ranks,
            "semantic_rank": semantic_ranks.get(row["claim_id"]),
            "surfaced_by": surfaced_by,
            "match_reasons": reasons,
            "differences": differences,
            "provenance": self.origin,
        }
