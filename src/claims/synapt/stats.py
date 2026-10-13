"""What the Synapt provider holds right now, read-only: documents, passages, the knowledge graph by kind, procedures, steps and
episodes. Shown on the Connection page so a reviewer sees the size and shape of the knowledge base the application relies on.

Two read calls (`trident_get_stats`, and `trident_episodes` in its inspect mode, which lists nothing and changes nothing),
cached for a minute so reloading the page does not call Synapt each time. It never raises: an unavailable provider is a
sentence on the page, not an error.
"""

import asyncio
import time
from datetime import UTC, datetime

from claims.agents import access
from claims.synapt.inventory import _unwrap

TTL_SECONDS = 60
# Node kinds that are the text itself or the provider record, not knowledge extracted from it.
_STRUCTURAL = {"Chunk", "Document", "Provider"}


def summarize(stats: dict, episodes: dict | None, fetched_at: str) -> dict:
    labels = stats.get("counts_by_label") or {}
    store = (episodes or {}).get("store") or {}
    return {
        "available": True,
        "provider_id": stats.get("provider_id"),
        "kind": stats.get("provider_kind"),
        "has_ticket_store": bool(stats.get("has_ticket_store")),
        "documents": stats.get("doc_count"),
        "passages": stats.get("chunks"),
        "graph_nodes": stats.get("nodes"),
        "connections": stats.get("edges"),
        "procedures": stats.get("procedures"),
        "steps": labels.get("Step"),
        "entities": stats.get("entities"),
        "concepts": stats.get("concepts"),
        "knowledge_by_kind": [
            {"kind": kind, "count": count}
            for kind, count in sorted(labels.items(), key=lambda item: (-item[1], item[0]))
            if kind not in _STRUCTURAL and isinstance(count, int)
        ],
        "episodes": {"store_exists": bool(store.get("exists")), "count": store.get("episode_count")} if episodes is not None else None,
        "fetched_at": fetched_at,
    }


def unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason}


class SynaptStats:
    def __init__(self, adapter, provider_id: str, ttl: float = TTL_SECONDS, clock=time.monotonic):
        self.adapter, self.provider_id, self.ttl, self.clock = adapter, provider_id, ttl, clock
        self._cached: tuple[float, dict] | None = None

    async def _fetch(self) -> dict:
        with access.acting_as("operator"):
            return await self._read()

    async def _read(self) -> dict:
        stats = _unwrap(await self.adapter.call_read_tool("trident_get_stats", {"provider_id": self.provider_id}))
        try:
            episodes = _unwrap(await self.adapter.call_read_tool("trident_episodes", {"provider_id": self.provider_id}))
        except Exception:  # noqa: BLE001 - the episode count is a nicety; the rest still shows
            episodes = None
        return summarize(stats | {"provider_id": self.provider_id}, episodes, datetime.now(UTC).isoformat())

    def get(self, refresh: bool = False) -> dict:
        """The provider's size and shape. Cached; an unavailable provider is returned as a reason, never raised."""
        if not hasattr(self.adapter, "call_read_tool"):
            return unavailable("Synapt is not connected in this environment.")
        now = self.clock()
        if not refresh and self._cached and now - self._cached[0] < self.ttl:
            return self._cached[1]
        try:
            result = asyncio.run(self._fetch())
        except Exception:  # noqa: BLE001 - provider errors never reach the page
            return self._cached[1] | {"stale": True} if self._cached else unavailable("Synapt could not be reached just now.")
        self._cached = (now, result)
        return result
