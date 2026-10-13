"""Literal-first saved-case autocomplete, with optional local semantic recall.

Inference never downloads models or sends queries/claims to a provider. The
public model is provisioned separately by scripts/prepare_case_search.py.
"""

import logging
import re
from collections import OrderedDict
from threading import RLock

import numpy as np

from claims.core.us_states import STATE_NAMES

logger = logging.getLogger(__name__)


def words(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def literal_rank(item, query):
    run_id = item["run_id"].casefold()
    if run_id == query:
        return 0, "Exact ID"
    if run_id.startswith(query):
        return 1, "ID prefix"
    if query in run_id:
        return 2, "ID match"
    title = words(item["title"])
    normalized = words(query)
    if normalized and title.startswith(normalized):
        return 3, "Title match"
    if normalized and normalized in title:
        return 4, "Title match"
    text = words(
        " ".join(
            [
                item["title"],
                item["description"],
                item["claim_type"] or "",
                item["state"],
                STATE_NAMES.get(item["state"], ""),
            ]
        )
    )
    if normalized and all(term in text for term in normalized.split()):
        return 5, "Text match"
    return None


class SavedCaseSearch:
    def __init__(self, store, settings, embedder=None):
        self.store, self.settings = store, settings
        self.model = embedder
        self.attempted = embedder is not None
        self.vectors = {}
        self.queries = OrderedDict()
        self.lock = RLock()

    def _model(self):
        if not self.attempted:
            self.attempted = True
            try:
                from fastembed import TextEmbedding

                self.model = TextEmbedding(
                    model_name=self.settings.claims_search_model,
                    cache_dir=str(self.settings.claims_search_cache_dir),
                    threads=2,
                    local_files_only=True,
                )
            except Exception as exc:  # noqa: BLE001 - optional model failure must preserve literal search
                # Do not log claim/query text or provider credentials.
                logger.warning("Local case-search model unavailable (%s)", type(exc).__name__)
        return self.model

    @staticmethod
    def _vector(vector):
        vector = np.asarray(vector, dtype=np.float32)
        if vector.ndim != 1 or not vector.size or not np.isfinite(vector).all():
            raise ValueError("Invalid embedding")
        norm = np.linalg.norm(vector)
        if norm <= 0:
            raise ValueError("Empty embedding")
        return vector / norm

    def _semantic(self, query, items):
        with self.lock:
            model = self._model()
            if model is None:
                return [], "unavailable"
            try:
                current_ids = {item["run_id"] for item in items}
                self.vectors = {k: v for k, v in self.vectors.items() if k in current_ids}
                pending = []
                for item in items:
                    text = f"{item['title']}\n{item['description']}"
                    cached = self.vectors.get(item["run_id"])
                    if cached is None or cached[0] != text:
                        pending.append((item["run_id"], text))
                vectors = (
                    list(model.passage_embed([text for _, text in pending])) if pending else []
                )
                if len(vectors) != len(pending):
                    raise ValueError("Embedding count mismatch")
                validated = [
                    (run_id, (text, self._vector(v))) for (run_id, text), v in zip(pending, vectors)
                ]
                self.vectors.update(validated)
                if query not in self.queries:
                    self.queries[query] = self._vector(next(iter(model.query_embed(query))))
                    if len(self.queries) > 64:
                        self.queries.popitem(last=False)
                vector = self.queries[query]
                matches = []
                for item in items:
                    score = float(np.dot(vector, self.vectors[item["run_id"]][1]))
                    if score >= self.settings.claims_search_min_similarity:
                        matches.append((score, item))
                matches.sort(key=lambda pair: pair[0], reverse=True)
                return matches, "ready"
            except Exception as exc:  # noqa: BLE001 - validate third-party model outputs before ranking
                self.vectors.clear()
                self.queries.clear()
                logger.warning("Local semantic search failed (%s)", type(exc).__name__)
                return [], "unavailable"

    def suggest(self, query, limit=8, owner_id=None):
        query = query.strip().casefold()
        items = self.store.search_documents(owner_id)
        if not query:
            return {
                "items": [dict(item, match_kind="Recently saved") for item in items[:limit]],
                "total": len(items),
                "semantic_status": "not_needed",
            }
        ranked = [(rank, item) for item in items if (rank := literal_rank(item, query))]
        ranked.sort(key=lambda pair: pair[0][0])  # Stable tie-break: newest saved first.
        found = [dict(item, match_kind=rank[1]) for rank, item in ranked]
        semantic_status = "not_needed"
        # IDs and short partial words must not produce unrelated semantic suggestions.
        if (
            self.settings.claims_search_enabled
            and len(query) >= 4
            and not re.fullmatch(r"[a-f0-9-]+", query)
            and items
        ):
            matches, semantic_status = self._semantic(query, items)
            literal_ids = {item["run_id"] for item in found}
            found.extend(
                dict(item, match_kind="Related meaning")
                for _, item in matches
                if item["run_id"] not in literal_ids
            )
        elif not self.settings.claims_search_enabled:
            semantic_status = "disabled"
        return {"items": found[:limit], "total": len(found), "semantic_status": semantic_status}
