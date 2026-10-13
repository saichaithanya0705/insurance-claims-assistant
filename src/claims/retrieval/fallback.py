"""Degraded-mode knowledge: a local copy of the procedures and a small local index over the cards.

Synapt is always tried first. This module is used only after a live Synapt call has failed, and every
run that uses it is labelled degraded (run mode, a limitation finding on the brief, the trace and the
health and integration status). It is not a way to run without Synapt: Settings still requires the
Synapt login and no setting selects this path.

What it provides, from files this repository can rebuild:

* the five handling procedures, the same text uploaded to Synapt (``claims.corpus.builder.SOPS``);
* a local semantic index over the profile cards (``claim_cards.parquet`` from
  ``scripts/build_profile_corpus.py``): each card's description is embedded with the same small local
  model the case search uses (fastembed, never downloaded at run time), or, if that model is not
  available, scored with TF-IDF. The ranked claim IDs go into the same place Synapt's would.

Nothing here talks to Synapt or to any other service.
"""

import hashlib
import logging
import re
from pathlib import Path
from threading import RLock

import duckdb
import numpy as np

from claims.core.schemas import ClaimInput, Evidence, RetrievalBundle
from claims.corpus.builder import SOPS, sop_document
from claims.corpus.cards import claim_card_text

logger = logging.getLogger(__name__)

# Worded to read well after the interface rewrites the vendor name, and without any coverage language.
DEGRADED_NOTICE = (
    "Degraded mode: the retrieval service was unavailable for this investigation, so the handling "
    "procedures and the similar-claim ranking came from a local copy of the procedures and a local "
    "index of past claims. Rankings can differ from live retrieval."
)

# Card text is "## history:<alias>", "claim_ref: <alias>", the description, an outcome sentence and a
# profile sentence. A query never states an outcome or a profile, so only the description is indexed.
_DESCRIPTION = re.compile(r"claim_ref:[^\n]*\n(.*?)(?:\s+Outcome\b|\s+Profile:|\s*$)", re.DOTALL)
_TOKEN = r"[\w][\w,\-.]*"


def description_of(card_text: str) -> str:
    match = _DESCRIPTION.search(card_text)
    return (match.group(1) if match else card_text).strip()


def _normalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


class LocalKnowledge:
    def __init__(self, settings, embedder=None):
        self.settings = settings
        self._embedder = embedder
        self._embedder_tried = embedder is not None
        self._lock = RLock()
        self._ids: list[str] = []
        self._vectors = None
        self._tfidf = None
        self.backend: str | None = None
        self.ready = False

    @property
    def cards_path(self) -> Path:
        return Path(self.settings.claims_fallback_cards_path)

    def available(self) -> bool:
        return bool(self.settings.claims_fallback_enabled) and self.cards_path.is_file()

    def status(self) -> dict:
        return {
            "enabled": bool(self.settings.claims_fallback_enabled),
            "cards_file_present": self.cards_path.is_file(),
            "ready": self.ready,
            "backend": self.backend,
            "cards": len(self._ids),
        }

    def _model(self):
        if not self._embedder_tried:
            self._embedder_tried = True
            try:
                from fastembed import TextEmbedding

                self._embedder = TextEmbedding(
                    model_name=self.settings.claims_search_model,
                    cache_dir=str(self.settings.claims_search_cache_dir),
                    threads=2,
                    local_files_only=True,
                )
            except Exception as exc:  # noqa: BLE001 - the TF-IDF backend covers a missing model
                logger.warning("Local embedding model unavailable (%s); using TF-IDF", type(exc).__name__)
        return self._embedder

    def _encode(self, texts: list[str]) -> np.ndarray:
        vectors = [np.asarray(v, dtype=np.float32) for v in self._model().embed(texts)]
        return _normalise(np.vstack(vectors))

    def warm(self) -> None:
        """Load or build the index. Safe to call from a background thread and to call twice."""
        with self._lock:
            if self.ready:
                return
            rows = duckdb.connect().execute(
                "SELECT claim_id, card_text FROM read_parquet(?) ORDER BY claim_id",
                [self.cards_path.as_posix()],
            ).fetchall()
            if not rows:
                raise ValueError("The local card file is empty")
            self._ids = [row[0] for row in rows]
            documents = [description_of(row[1]) for row in rows]
            if self._model() is not None:
                digest = hashlib.sha256(self.cards_path.read_bytes()).hexdigest()[:16]
                model_tag = re.sub(r"\W+", "_", str(self.settings.claims_search_model))
                cache = Path(self.settings.claims_fallback_index_dir) / f"{digest}-{model_tag}.npy"
                if cache.is_file():
                    vectors = np.load(cache)
                    if vectors.shape[0] != len(documents):
                        vectors = None
                else:
                    vectors = None
                if vectors is None:
                    vectors = self._encode(documents)
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    np.save(cache, vectors)
                self._vectors, self.backend = vectors, "embeddings"
            else:
                from sklearn.feature_extraction.text import TfidfVectorizer

                self._tfidf = TfidfVectorizer(token_pattern=_TOKEN, lowercase=True, sublinear_tf=True)
                self._vectors = self._tfidf.fit_transform(documents)
                self.backend = "tfidf"
            self.ready = True
            logger.info("Local fallback index ready (%s, %d cards)", self.backend, len(self._ids))

    def search(self, query: str, k: int) -> list[str]:
        """Claim IDs of the cards closest to ``query``, best first."""
        self.warm()
        if self.backend == "embeddings":
            scores = self._vectors @ self._encode([query])[0]
        else:
            scores = (self._vectors @ self._tfidf.transform([query]).T).toarray().ravel()
        order = np.argsort(-scores, kind="stable")[:k]
        return [self._ids[i] for i in order]

    @staticmethod
    def procedures() -> list[Evidence]:
        return [
            Evidence(
                source_id=f"local:{source_id}",
                title=title,
                text=sop_document(source_id, title, body),
                provenance="local_copy",
                provider_id=None,
            )
            for source_id, title, body in SOPS
        ]

    def retrieve(self, claim: ClaimInput) -> RetrievalBundle:
        query = claim_card_text(claim.model_dump(mode="json"), include_outcome=False, masking_safe=True)
        return RetrievalBundle(
            mode="degraded",
            evidence=self.procedures(),
            warnings=[DEGRADED_NOTICE],
            semantic_claim_ids=self.search(query, self.settings.synapt_case_top_k),
        )
