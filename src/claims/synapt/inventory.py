"""Verify, from Synapt's own graph, that the provider holds the corpus this project expects.

Reading chunks back cannot prove completeness. One query returns at most about 1,900 chunks and
the tenant rejects a ``top_k`` near the provider's 20,914 chunks, so a retrieval inventory is partial
by construction (see docs/SYNAPT_INTEGRATION.md). The graph answers exactly: every document records
its chunk count, and its chunk nodes carry character spans.

A document is accepted when all of these hold:

* it is identified: an expansion batch by the marker in its header chunk (the chunk also carries the
  document's ``source_file``); a base batch by chunk count and text length, because base batches have
  no marker;
* its chunk count equals the batch's card count (cards are one chunk each, plus a chunk or two when a
  page header splits a chunk);
* every chunk node is linked and the text starts at character 0;
* its last ``char_end`` equals the local batch text length plus a wrapper that Synapt adds per
  document. Sibling batches share one wrapper, so a document that is a card short sits about 300
  characters away from its siblings and fails.

Synapt masks personal-looking text before indexing. A 9-digit run inside a batch marker becomes
``[US_SSN_<hash>]``; :func:`marker_pattern` tolerates that rewrite and nothing else.

The expected inventory lives in ``data/synapt/expected_inventory.json`` so every machine compares the
live provider against the same committed expectation instead of a local, git-ignored upload ledger.
"""

import json
import re
import statistics
from datetime import UTC, datetime
from pathlib import Path

from claims.agents import access

INVENTORY_PATH = Path("data/synapt/expected_inventory.json")
CHUNK_SLACK = 2  # chunks a document may hold beyond its card count
OFFSET_TOLERANCE = 50  # characters sibling batches may differ in wrapper; a missing card is ~300
MAX_WRAPPER = 5_000  # per-document page headers measured at 0.3 to 1.1 thousand characters
HEADER_QUERY = "Historical claim cards; corpus batch cardpack_"
DOCUMENT_QUERY = (
    "MATCH (d:Document {provider_id: $provider_id})-[:CONTAINS]->(c:Chunk) "
    "RETURN d.filename AS f, d.chunk_count AS n, count(c) AS linked, "
    "min(c.char_start) AS lo, max(c.char_end) AS hi ORDER BY hi LIMIT 500"
)
_MASKED_RUN = re.compile(r"\d{7,}")
_MASK_TOKEN = r"\[[A-Z_]+_[0-9a-f]+\]"
_SOURCE_ID = re.compile(r"source_id:\s*(\S+)")
# A procedure is one chunk; Synapt's own episodic document (`es_<provider>`) grows with use. A larger document in a provider
# that should hold no card batches is a leftover batch.
LEFTOVER_CHUNKS = 100


def marker_pattern(marker: str) -> re.Pattern[str]:
    """Match a batch marker, allowing a long digit run to be masked by Synapt's PII filter."""
    parts: list[str] = []
    last = 0
    for run in _MASKED_RUN.finditer(marker):
        parts.append(re.escape(marker[last : run.start()]))
        parts.append(f"(?:{re.escape(run.group())}|\\d*{_MASK_TOKEN}\\d*)")
        last = run.end()
    parts.append(re.escape(marker[last:]))
    return re.compile("".join(parts))


def load_expected(path: Path | str = INVENTORY_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _batch_entries(corpus: Path, with_marker: bool) -> list[dict]:
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    entries = []
    for batch in manifest["batches"]:
        text = (corpus / batch["path"]).read_text(encoding="utf-8")
        entry = {
            "name": Path(batch["path"]).name,
            "cards": batch.get("cards") or len(batch["claim_ids"]),
            "chars": len(text),
            "sha256": batch["sha256"],
        }
        if with_marker:
            entry["marker"] = batch["marker"]
        entries.append(entry)
    return entries


def build_expected(
    base_dir: Path | None, expansion_dir: Path, verified_stats: dict | None = None
) -> dict:
    """Describe local corpora in the form :func:`verify_store` compares against live Synapt.

    ``base_dir`` may be None for a provider that holds only marker-headed batches (a single
    corpus, such as the profile corpus); its procedures then come from ``expansion_dir``."""
    procedures = sorted(
        _SOURCE_ID.search(path.read_text(encoding="utf-8")).group(1)
        for path in ((base_dir or expansion_dir) / "procedures").glob("*.txt")
    )
    return {
        "schema_version": 1,
        "note": "Regenerate with: uv run python scripts/verify_synapt_store.py --write-expected",
        "verified_against_synapt": verified_stats or {},
        "base": {"batches": _batch_entries(base_dir, with_marker=False) if base_dir else []},
        "expansion": {"batches": _batch_entries(expansion_dir, with_marker=True)},
        "procedures": procedures,
    }


def _unwrap(payload):
    result = payload.get("result", payload) if isinstance(payload, dict) else payload
    return json.loads(result) if isinstance(result, str) else result


async def _chunks(adapter, provider: str, query: str, top_k: int) -> list[dict]:
    payload = _unwrap(
        await adapter.call_read_tool(
            "trident_get_chunks",
            {"provider_id": provider, "query": query, "top_k": top_k},
            max_response_chars=5_000_000,
        )
    )
    return payload if isinstance(payload, list) else payload.get("chunks", [])


def _check_document(batch: dict, doc: dict) -> tuple[int, list[str]]:
    reasons = []
    cards = batch["cards"]
    if not cards <= doc["n"] <= cards + CHUNK_SLACK:
        reasons.append(f"holds {doc['n']} chunks for {cards} cards")
    if doc["linked"] != doc["n"]:
        reasons.append(f"{doc['linked']} chunk nodes linked but the document records {doc['n']}")
    if doc["lo"] != 0:
        reasons.append("text does not start at character 0")
    offset = doc["hi"] - batch["chars"]
    if not 0 <= offset <= MAX_WRAPPER:
        reasons.append(f"text spans {doc['hi']} characters against {batch['chars']} locally")
    return offset, reasons


def _check_siblings(results: list[dict]) -> None:
    """Batches with the same card count share one wrapper; an outlier is missing or gained content."""
    groups: dict[int, list[dict]] = {}
    for result in results:
        if result.get("offset") is not None:
            groups.setdefault(result["cards"], []).append(result)
    for group in groups.values():
        if len(group) < 2:  # a lone batch is checked only against the wrapper bounds
            continue
        median = statistics.median(r["offset"] for r in group)
        # With two siblings the median sits halfway between them, so halve the limit: they must agree.
        limit = OFFSET_TOLERANCE if len(group) > 2 else OFFSET_TOLERANCE / 2
        for result in group:
            if abs(result["offset"] - median) > limit:
                result["reasons"].append(
                    f"text length is {result['offset'] - median:+.0f} characters from sibling batches"
                )


def _finish(results: list[dict]) -> list[dict]:
    for result in results:
        if result["status"] != "unidentified":
            result["status"] = "failed" if result["reasons"] else "verified"
    return results


async def _verify_expansion(adapter, provider: str, batches: list[dict], documents: dict) -> list[dict]:
    headers = await _chunks(adapter, provider, HEADER_QUERY, 200)

    def source_of(chunks: list[dict], pattern: re.Pattern[str]) -> str | None:
        return next((c.get("source_file") for c in chunks if pattern.search(c.get("text", ""))), None)

    results = []
    for batch in batches:
        pattern = marker_pattern(batch["marker"])
        source = source_of(headers, pattern)
        if source is None:  # not among the bulk header hits: ask for this marker on its own
            extra = await _chunks(adapter, provider, f"corpus batch {batch['marker']}", 20)
            source = source_of(extra, pattern)
        result = {"name": batch["name"], "cards": batch["cards"], "source_file": source,
                  "status": "verified", "chunks": None, "offset": None, "reasons": []}
        if source is None:
            result["status"] = "unidentified"
            result["reasons"].append("no document header carries this batch marker")
        elif source not in documents:
            result["reasons"].append("document is not in the graph")
        else:
            result["chunks"] = documents[source]["n"]
            result["offset"], result["reasons"] = _check_document(batch, documents[source])
        results.append(result)
    claimed: dict[str, int] = {}
    for result in results:
        if result["source_file"]:
            claimed[result["source_file"]] = claimed.get(result["source_file"], 0) + 1
    for result in results:
        if result["source_file"] and claimed[result["source_file"]] > 1:
            result["reasons"].append("another batch maps to the same document")
    _check_siblings(results)
    return _finish(results)


def _verify_base(batches: list[dict], documents: dict, taken: set[str]) -> list[dict]:
    """Base batches carry no marker: pair them with documents by size, then check the text spans."""
    cards = {b["cards"] for b in batches}
    candidates = sorted(
        (d for f, d in documents.items()
         if f not in taken and any(c <= d["n"] <= c + CHUNK_SLACK for c in cards)),
        key=lambda d: d["hi"],
    )
    ordered = sorted(batches, key=lambda b: (b["chars"], b["name"]))
    results = []
    if len(candidates) != len(ordered):
        for batch in ordered:
            results.append({"name": batch["name"], "cards": batch["cards"], "source_file": None,
                            "status": "unidentified", "chunks": None, "offset": None,
                            "reasons": [f"{len(candidates)} candidate documents for {len(ordered)} batches"]})
        return results
    for batch, doc in zip(ordered, candidates):
        offset, reasons = _check_document(batch, doc)
        results.append({"name": batch["name"], "cards": batch["cards"], "source_file": doc["f"],
                        "status": "verified", "chunks": doc["n"], "offset": offset, "reasons": reasons})
    _check_siblings(results)
    return _finish(results)


async def _procedure_present(adapter, provider: str, source_id: str) -> bool:
    chunks = await _chunks(
        adapter, provider, f"{source_id} source_id: {source_id} hand-authored synthetic procedure", 10
    )
    return any(source_id.lower() in c.get("text", "").lower() for c in chunks)


def _section(results: list[dict]) -> dict:
    verified = [r for r in results if r["status"] == "verified"]
    return {
        "expected": len(results),
        "verified": len(verified),
        "cards_verified": sum(r["cards"] for r in verified),
        "cards_expected": sum(r["cards"] for r in results),
        "batches": results,
    }


async def verify_store(adapter, provider: str, expected: dict) -> dict:
    with access.acting_as("operator"):
        return await _verify_store(adapter, provider, expected)


async def _verify_store(adapter, provider: str, expected: dict) -> dict:
    """Read-only comparison of the live provider with ``expected``; never writes to Synapt."""
    stats = _unwrap(await adapter.call_read_tool("trident_get_stats", {"provider_id": provider}))
    rows = _unwrap(
        await adapter.call_read_tool(
            "trident_cypher", {"provider_id": provider, "query": DOCUMENT_QUERY}
        )
    )
    rows = rows if isinstance(rows, list) else rows.get("rows", [])
    documents = {row["f"]: row for row in rows}
    expansion = await _verify_expansion(adapter, provider, expected["expansion"]["batches"], documents)
    taken = {r["source_file"] for r in expansion if r["source_file"]}
    base = _verify_base(expected["base"]["batches"], documents, taken)
    procedures = {sid: await _procedure_present(adapter, provider, sid) for sid in expected["procedures"]}

    expansion_section = _section(expansion)
    if not expansion:
        state = "none"  # the provider is meant to hold no card batches (claims live in its ticket store)
    elif expansion_section["verified"] == expansion_section["expected"]:
        state = "complete"
    elif all(r["status"] == "unidentified" for r in expansion):
        state = "absent"  # optional corpus: the application only needs base cards and procedures
    else:
        state = "incomplete"
    expansion_section["state"] = state
    base_section = _section(base)
    matched = {r["source_file"] for r in (*base, *expansion) if r["status"] == "verified"}
    leftovers = (
        sorted(f for f, row in documents.items() if not str(f).startswith("es_") and (row.get("linked") or 0) > LEFTOVER_CHUNKS)
        if not expected["base"]["batches"] and not expected["expansion"]["batches"]
        else []
    )
    tickets = _check_tickets(stats, expected.get("tickets"))
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "provider": provider,
        "stats": {"documents": stats.get("doc_count"), "chunks": stats.get("chunks"),
                  "documents_listed": len(documents), "documents_matched_to_batches": len(matched)},
        "base": base_section,
        "expansion": expansion_section,
        "procedures": procedures,
        "tickets": tickets,
        "leftover_documents": leftovers,
        "ok": base_section["verified"] == base_section["expected"]
        and all(procedures.values())
        and state != "incomplete"
        and not leftovers
        and (tickets is None or not tickets["problems"]),
    }


def _check_tickets(stats: dict, want: dict | None) -> dict | None:
    """The ticket store as ``trident_get_stats`` reports it, against the uploaded workbook. None when none is expected."""
    if not want:
        return None
    mining = stats.get("ticket_mining") or {}
    problems = []
    if not stats.get("has_ticket_store"):
        problems.append("the provider has no ticket store")
    else:
        if mining.get("tickets") != want["tickets"]:
            problems.append(f"{mining.get('tickets')} tickets, expected {want['tickets']}")
        if mining.get("id_field") != want["id_field"]:
            problems.append(f"ID column is {mining.get('id_field')}, expected {want['id_field']}")
        if sorted(mining.get("label_fields") or []) != sorted(want["label_fields"]):
            problems.append(f"label fields are {mining.get('label_fields')}, expected {want['label_fields']}")
    return {"expected": want["tickets"], "found": mining.get("tickets"), "held_out": mining.get("held_out"),
            "label_fields": mining.get("label_fields"), "problems": problems}


def summary_lines(report: dict) -> list[tuple[str, str]]:
    """(mark, text) pairs for CLI output: ``ok`` verified, ``..`` informational, ``XX`` problem."""
    base, expansion, procedures = report["base"], report["expansion"], report["procedures"]
    base_text = (
        f"base corpus: {base['verified']}/{base['expected']} batches verified "
        f"({base['cards_verified']:,} of {base['cards_expected']:,} cards)"
    )
    # A provider with a single corpus has no base section; don't print an empty "0/0" line for it.
    lines = [("ok" if base["verified"] == base["expected"] else "XX", base_text)] if base["expected"] else []
    if expansion["state"] == "complete":
        text = (
            f"expansion corpus: {expansion['verified']}/{expansion['expected']} batches "
            f"verified ({expansion['cards_verified']:,} cards)"
        )
        lines.append(("ok", text))
    elif expansion["state"] == "none":
        pass
    elif expansion["state"] == "absent":
        text = "expansion corpus: not ingested (optional; the app needs only the base cards)"
        lines.append(("..", text))
    else:
        text = f"expansion corpus: {expansion['verified']}/{expansion['expected']} batches verified"
        lines.append(("XX", text))
    found = f"procedures: {sum(procedures.values())}/{len(procedures)} found by source id"
    lines.append(("ok" if all(procedures.values()) else "XX", found))
    # An absent optional corpus is one informational line, not forty failures; base is always itemised.
    itemised = base["batches"] if expansion["state"] == "absent" else (*base["batches"], *expansion["batches"])
    for result in itemised:
        if result["status"] != "verified":
            lines.append(("XX", f"{result['name']}: {result['status']}: {'; '.join(result['reasons'])}"))
    lines.extend(("XX", f"procedure {sid} not found") for sid, present in procedures.items() if not present)
    tickets = report.get("tickets")
    if tickets is not None:
        if tickets["problems"]:
            lines.append(("XX", "ticket store: " + "; ".join(tickets["problems"])))
        else:
            text = (
                f"ticket store: {tickets['found']:,} tickets ({tickets['held_out']} held out by Synapt), "
                f"labels {', '.join(tickets['label_fields'])}"
            )
            lines.append(("ok", text))
    for name in report.get("leftover_documents", []):
        lines.append(("XX", f"leftover document {name}: not a procedure, and too large for one"))
    stats = report["stats"]
    if expansion["state"] == "none":
        others = f"{stats['documents']} documents in all, {stats['chunks']} chunks: procedures and Synapt's own episode memory"
    else:
        others = (
            f"{stats['documents']} documents in all; {stats['documents_matched_to_batches']} matched to "
            "corpus batches, the rest are procedures, lessons and probes"
        )
    lines.append(("..", others))
    return lines
