"""The cohort figures from three small tables instead of a scan of 100 million rows.

`claims.history.cohort` answers "how were claims like this one settled?" with exact counts, approval shares, flag rates and the 25th, 50th
and 75th percentile of days to settle, for three groups of past claims. Measured on 12 October, that scan took 5 to 10 s, and it
is the longest step of an investigation. The groups are fixed (the same description, the same type with the same amount and history
bands, the same type), so one pass over the dataset can count every group once and keep the result:

* ``cohort_exact``  one row per description (type, state and the amount, tenure, history and filing-delay bands),
* ``cohort_tah``    one row per type, amount band and history band,
* ``cohort_type``   one row per type,

each with the number of settled claims, how many were approved, denied and flagged, and the **histogram of days to settle**. Days are
whole numbers (126 distinct values, 0 to 134, none fractional), so a percentile read from the histogram is the same number
``quantile_cont`` gives on the rows: the two are checked against each other when the summary is built and in the tests.

A summary is only used when it provably belongs to the file it is asked about: it records the dataset's SHA-256, the cutoff date, the
band edges and its own version, and `CohortSummary.open` returns nothing (and the scan runs, as before) if any of them differ. A
stale summary can never be served.
"""

import json
import logging
import math
import time
from datetime import date
from pathlib import Path

import duckdb

from claims.corpus.cards import AMOUNT_EDGES, DELAY_EDGES, TENURE_EDGES
from claims.corpus.profile_cards import _eligible_sql
from claims.history.dataset import ClaimsStore

logger = logging.getLogger(__name__)

VERSION = 1
QUANTILES = (0.25, 0.5, 0.75)
# `GROUPING(state, amount_idx, tenure_idx, history_idx, delay_idx)` of each grouping set, which tells the rows apart.
G_EXACT, G_TAH, G_TYPE = 0, 0b10101, 0b11111
LEVELS = {
    "exact": ("cohort_exact", ("claim_type", "state", "amount_idx", "tenure_idx", "history_idx", "delay_idx")),
    "type_amount_history": ("cohort_tah", ("claim_type", "amount_idx", "history_idx")),
    "type": ("cohort_type", ("claim_type",)),
}


def _identity(store: ClaimsStore, cutoff: date) -> dict:
    return {
        "version": VERSION,
        "source_sha256": store.fingerprint()["source_file_sha256"],
        "cutoff": cutoff.isoformat(),
        "edges": {"amount": list(AMOUNT_EDGES), "tenure": list(TENURE_EDGES), "delay": list(DELAY_EDGES)},
    }


def pairs(days) -> list[tuple[int, int]]:
    """A histogram as DuckDB returns it (a MAP) turned into sorted (days, claims) pairs."""
    if days is None:
        return []
    if isinstance(days, dict) and set(days) == {"key", "value"}:
        items = zip(days["key"], days["value"], strict=True)
    elif isinstance(days, dict):
        items = days.items()
    else:
        items = days
    return sorted((int(k), int(v)) for k, v in items)


def quantiles_from_histogram(histogram: list[tuple[int, int]], fractions=QUANTILES) -> list[float] | None:
    """``quantile_cont`` of the values a histogram stands for: linear interpolation at position q * (n - 1) of the sorted values."""
    total = sum(count for _, count in histogram)
    if not total:
        return None
    ends, running = [], 0
    for _, count in histogram:
        running += count
        ends.append(running)

    def value_at(index: int) -> int:
        lo, hi = 0, len(ends) - 1  # first bucket whose running total passes the index
        while lo < hi:
            mid = (lo + hi) // 2
            if ends[mid] > index:
                hi = mid
            else:
                lo = mid + 1
        return histogram[lo][0]

    out = []
    for q in fractions:
        position = q * (total - 1)
        low, high = math.floor(position), math.ceil(position)
        a, b = value_at(low), value_at(high)
        out.append(float(a + (position - low) * (b - a)))
    return out


def build(store: ClaimsStore, path: Path, cutoff: date) -> dict:
    """One pass over the dataset into a new summary file. Returns what was built and how long it took."""
    started = time.perf_counter()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".building")
    tmp.unlink(missing_ok=True)
    fractional = store._run(
        f"""SELECT count(*) AS n FROM ({_eligible_sql(store)}) WHERE days_to_resolution != floor(days_to_resolution)""", [cutoff]
    )[0]["n"]
    if fractional:
        raise ValueError(f"{fractional:,} settled claims have fractional days; a histogram of whole days would not be exact")
    eligible = _eligible_sql(store, ", is_fraud_flagged_ground_truth")
    identity = _identity(store, cutoff)
    with store.lock:  # the whole build happens inside DuckDB: no row crosses into Python
        con = store.connection
        con.execute(f"ATTACH '{tmp.as_posix()}' AS summary")
        try:
            con.execute(
                f"""
                CREATE TEMP TABLE grouped AS
                SELECT claim_type, state, amount_idx, tenure_idx, history_idx, delay_idx,
                       GROUPING(state, amount_idx, tenure_idx, history_idx, delay_idx) AS g,
                       count(*) AS n,
                       count(*) FILTER (WHERE claim_status = 'approved') AS approved,
                       count(*) FILTER (WHERE claim_status = 'denied') AS denied,
                       count(*) FILTER (WHERE is_fraud_flagged_ground_truth) AS flagged,
                       histogram(CAST(days_to_resolution AS INTEGER)) AS days
                FROM ({eligible})
                GROUP BY GROUPING SETS (
                    (claim_type, state, amount_idx, tenure_idx, history_idx, delay_idx),
                    (claim_type, amount_idx, history_idx),
                    (claim_type)
                )
                """,
                [cutoff],
            )
            counts = {}
            for level, (table, keys) in LEVELS.items():
                g = {"exact": G_EXACT, "type_amount_history": G_TAH, "type": G_TYPE}[level]
                con.execute(
                    f"CREATE TABLE summary.{table} AS SELECT {', '.join(keys)}, n, approved, denied, flagged, days FROM grouped WHERE g = {g}"
                )
                counts[table] = con.execute(f"SELECT count(*) FROM summary.{table}").fetchone()[0]
            con.execute("CREATE TABLE summary.meta (key VARCHAR, value VARCHAR)")
            for key, value in identity.items():
                con.execute("INSERT INTO summary.meta VALUES (?, ?)", [key, json.dumps(value)])
            con.execute("DROP TABLE grouped")
        finally:
            con.execute("DETACH summary")
    path.unlink(missing_ok=True)
    tmp.replace(path)
    return {"path": str(path), "rows": counts, "seconds": round(time.perf_counter() - started, 1), "identity": identity}


class CohortSummary:
    """Read-only access to a summary that belongs to the dataset in use."""

    def __init__(self, connection):
        self.connection = connection

    @classmethod
    def open(cls, path: Path | None, store: ClaimsStore | None, cutoff: date):
        """The summary, or None when there is none or it is not for this dataset, cutoff and band edges."""
        if path is None or store is None or not Path(path).is_file():
            return None
        try:
            connection = duckdb.connect(str(path), read_only=True)
            stored = {k: json.loads(v) for k, v in connection.execute("SELECT key, value FROM meta").fetchall()}
            expected = json.loads(json.dumps(_identity(store, cutoff)))
            if stored != expected:
                connection.close()
                logger.warning("Cohort summary at %s is not for this dataset; scanning instead", path)
                return None
            return cls(connection)
        except (duckdb.Error, OSError, ValueError, KeyError) as error:
            logger.warning("Cohort summary at %s could not be used (%s); scanning instead", path, type(error).__name__)
            return None

    def aggregate(self, cell: dict) -> dict:
        """The same row the scan returns: for each group its claims, approved, denied, flagged and 25th/50th/75th percentile days."""
        row = {}
        for level, (table, keys) in LEVELS.items():
            condition = " AND ".join(f"{k} = ?" for k in keys)
            found = self.connection.execute(
                f"SELECT n, approved, denied, flagged, days FROM {table} WHERE {condition}", [cell[k] for k in keys]
            ).fetchone()
            n, approved, denied, flagged, days = found if found else (0, 0, 0, 0, None)
            row |= {
                f"{level}_claims": n,
                f"{level}_approved": approved,
                f"{level}_denied": denied,
                f"{level}_flagged": flagged,
                f"{level}_days": quantiles_from_histogram(pairs(days)),
            }
        return row

    def close(self):
        self.connection.close()
