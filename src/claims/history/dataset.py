"""DuckDB access to the full 100-million-row claims Parquet file.

The file stays on disk and is queried in place: filters, historical-availability rules and the
feature-similarity score run inside DuckDB, so only a few hundred candidate rows ever reach Python.
Training also draws its sample here. Nothing in this module writes to the dataset.
"""

import hashlib
import json
import math
import threading
import time
from datetime import date
from pathlib import Path

import duckdb

COLUMNS = (
    "claim_id",
    "policy_id",
    "claim_type",
    "state",
    "policyholder_tenure_years",
    "previous_claims_count",
    "incident_date",
    "claim_filed_date",
    "claim_amount",
    "deductible",
    "claim_status",
    "days_to_resolution",
    "is_fraud_flagged_ground_truth",
)
# The sorted native copy (see ClaimsStore.attach_copy): bump this when its layout changes, so an old file is never used.
COPY_VERSION = 1
COPY_ORDER = ("claim_type", "state", "claim_amount")
# When a settled claim closed, written once into the copy; the Parquet file computes it per row for every search.
CLOSED_EXPRESSION = "claim_filed_date + TRY_CAST(floor(days_to_resolution) AS INTEGER)"
CLOSED_STATUSES = ("approved", "denied")
OPEN_STATUSES = ("pending", "under_review")
DATASET = "ziadatalabs/FreeInsuranceClaims100M"
FILENAME = "insurance_claims_100M.parquet"


def _clean(row: dict) -> dict:
    """Plain JSON-safe types; Parquet stores a missing duration as NaN, which must become None."""
    out = dict(row)
    for key in ("incident_date", "claim_filed_date"):
        out[key] = out[key].isoformat() if isinstance(out[key], date) else str(out[key])[:10]
    for key in ("policyholder_tenure_years", "claim_amount", "deductible", "days_to_resolution"):
        value = out.get(key)
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            out[key] = None
        else:
            out[key] = round(float(value), 2)
    out["previous_claims_count"] = int(out["previous_claims_count"])
    out["is_fraud_flagged_ground_truth"] = bool(out["is_fraud_flagged_ground_truth"])
    return out


class ClaimsStore:
    def __init__(self, path, *, memory_limit: str = "3GB", threads: int | None = None):
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"Claims Parquet file not found: {self.path}")
        if "'" in str(self.path):
            raise ValueError("Parquet path must not contain a single quote")
        self.lock = threading.Lock()
        self.copy_alias: str | None = None
        self.connection = duckdb.connect(":memory:")
        self.connection.execute(f"SET memory_limit='{memory_limit}'")
        if threads:
            self.connection.execute(f"SET threads={int(threads)}")
        self.source = f"read_parquet('{self.path.as_posix()}')"
        self._count = None
        self._fingerprint = None

    def _run(self, sql: str, params=()) -> list[dict]:
        with self.lock:
            cursor = self.connection.execute(sql, list(params))
            names = [d[0] for d in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]

    def rows(self, sql: str, params=()) -> list[dict]:
        """Run a read-only query whose result has the 13 claim columns; returns cleaned rows."""
        return [_clean(r) for r in self._run(sql, params)]

    def row_count(self) -> int:
        if self._count is None:
            self._count = self._run(f"SELECT count(*) AS n FROM {self.source}")[0]["n"]
        return self._count

    def fingerprint(self) -> dict:
        """Source identity for model provenance; the SHA256 is cached beside the file."""
        if self._fingerprint is None:
            stat = self.path.stat()
            sidecar = self.path.with_name(self.path.name + ".fingerprint.json")
            cached = None
            if sidecar.exists():
                try:
                    cached = json.loads(sidecar.read_text(encoding="utf-8"))
                except ValueError:
                    cached = None
            if not cached or cached.get("bytes") != stat.st_size:
                digest = hashlib.sha256()
                with self.path.open("rb") as stream:
                    for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                        digest.update(block)
                cached = {"bytes": stat.st_size, "sha256": digest.hexdigest()}
                try:
                    sidecar.write_text(json.dumps(cached), encoding="utf-8")
                except OSError:
                    pass
            self._fingerprint = {
                "dataset": DATASET,
                "file": self.path.name,
                "bytes": cached["bytes"],
                "source_file_sha256": cached["sha256"],
                "rows": self.row_count(),
            }
        return self._fingerprint

    def _eligibility(self, status, before: date, closed: str = CLOSED_EXPRESSION):
        """Historical availability: a claim is comparable only if it was already settled (closed
        statuses) or already on file (open statuses) before the new claim was filed."""
        if status in OPEN_STATUSES:
            return ["claim_status = ?", "claim_filed_date < ?"], [status, before]
        statuses = [status] if status else list(CLOSED_STATUSES)
        marks = ",".join("?" for _ in statuses)
        return [
            f"claim_status IN ({marks})",
            # Parquet stores pending durations as NaN; TRY_CAST turns that into NULL (excluded).
            f"{closed} < ?",
        ], [*statuses, before]

    def _filter_clauses(self, filters, before: date, closed: str = CLOSED_EXPRESSION):
        clauses, params = self._eligibility(filters.claim_status, before, closed)
        if filters.claim_type:
            clauses.append("claim_type = ?")
            params.append(filters.claim_type.value)
        if filters.state:
            clauses.append("state = ?")
            params.append(filters.state)
        clauses.append("claim_amount BETWEEN ? AND ?")
        params += [filters.min_amount, filters.max_amount]
        clauses.append("previous_claims_count BETWEEN ? AND ?")
        params += [filters.min_previous_claims, filters.max_previous_claims]
        return clauses, params

    @staticmethod
    def _score(claim):
        sql = (
            "(CASE WHEN claim_type = ? THEN 2 ELSE 0 END) + (CASE WHEN state = ? THEN 1 ELSE 0 END)"
            " + 1.0/(1+abs(ln(1+claim_amount)-ln(1+?))) + 1.0/(1+abs(previous_claims_count-?))"
        )
        kind = claim.claim_type.value if claim.claim_type else None
        return sql, [kind, claim.state, claim.claim_amount, claim.previous_claims_count]

    def candidates(
        self, claim, filters, *, limit: int = 300, pool_by_type: bool = True, ids=None
    ) -> list[dict]:
        """Most similar eligible historical claims. ``ids`` (for example Synapt semantic matches)
        are looked up directly under the same filters instead of competing on the feature score."""
        # The pool search reads the sorted native copy when there is one that belongs to this dataset; a lookup by claim ID
        # stays on the Parquet file, whose row-group statistics find an ID without a scan.
        copy = self.copy_alias is not None and not ids
        clauses, params = self._filter_clauses(filters, claim.claim_filed_date, "closed_date" if copy else CLOSED_EXPRESSION)
        source = f"{self.copy_alias}.claims" if copy else self.source
        score_sql, score_params = self._score(claim)
        columns = ", ".join(COLUMNS)
        # Comparable claims share the new claim's type unless the handler filtered explicitly. The
        # same pool applies to semantic IDs: a "related meaning" claim of another type is not similar.
        if pool_by_type and claim.claim_type and not filters.claim_type:
            clauses.append("claim_type = ?")
            params.append(claim.claim_type.value)
        if ids:
            marks = ",".join("?" for _ in ids)
            sql = f"SELECT {columns}, {score_sql} AS feature_score FROM {self.source} WHERE " + " AND ".join(
                [f"claim_id IN ({marks})", *clauses]
            )
            return [_clean(r) for r in self._run(sql, [*score_params, *ids, *params])]
        sql = (
            f"SELECT {columns}, {score_sql} AS feature_score FROM {source} WHERE "
            + " AND ".join(clauses)
            + " ORDER BY feature_score DESC, claim_id LIMIT ?"
        )
        return [_clean(r) for r in self._run(sql, [*score_params, *params, limit])]

    def sample(self, rows: int, seed: int = 42) -> list[dict]:
        """Repeatable uniform random sample used for model training."""
        sql = (
            f"SELECT {', '.join(COLUMNS)} FROM {self.source} "
            f"USING SAMPLE reservoir({int(rows)} ROWS) REPEATABLE ({int(seed)})"
        )
        return [_clean(r) for r in self._run(sql)]

    def overview(self) -> dict:
        rows = self._run(
            f"SELECT claim_status, count(*) AS n FROM {self.source} GROUP BY claim_status ORDER BY n DESC"
        )
        return {
            "rows": self.row_count(),
            "by_status": {r["claim_status"]: r["n"] for r in rows},
        }

    # ----- the sorted native copy ------------------------------------------------------------------------------------------

    def build_copy(self, path: Path) -> dict:
        """Write a copy of the dataset in DuckDB's own format, sorted by type, state and amount, with the closing date of each claim
        computed once. The search for the closest claims scans it in about 1.4 s instead of 3 to 4 s on the Parquet file. It records
        the dataset's SHA-256, its row count and its layout, and `attach_copy` refuses it for anything else. Takes about 5 minutes."""
        started = time.perf_counter()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".building")
        for leftover in (tmp, tmp.with_name(tmp.name + ".wal")):
            leftover.unlink(missing_ok=True)
        identity = self._copy_identity()
        columns = ", ".join(COLUMNS)
        with self.lock:
            self.connection.execute(f"ATTACH '{tmp.as_posix()}' AS building")
            try:
                self.connection.execute(
                    f"CREATE TABLE building.claims AS SELECT {columns}, {CLOSED_EXPRESSION} AS closed_date FROM {self.source} "
                    f"ORDER BY {', '.join(COPY_ORDER)}"
                )
                self.connection.execute("CREATE TABLE building.meta (key VARCHAR, value VARCHAR)")
                for key, value in identity.items():
                    self.connection.execute("INSERT INTO building.meta VALUES (?, ?)", [key, json.dumps(value)])
                copied = self.connection.execute("SELECT count(*) FROM building.claims").fetchone()[0]
            finally:
                self.connection.execute("DETACH building")
        if copied != identity["rows"]:
            tmp.unlink(missing_ok=True)
            raise ValueError(f"The copy holds {copied:,} rows, the dataset {identity['rows']:,}")
        path.unlink(missing_ok=True)
        tmp.replace(path)
        return {"path": str(path), "rows": copied, "bytes": path.stat().st_size, "seconds": round(time.perf_counter() - started, 1)}

    def _copy_identity(self) -> dict:
        return {
            "version": COPY_VERSION,
            "source_sha256": self.fingerprint()["source_file_sha256"],
            "rows": self.row_count(),
            "columns": list(COLUMNS),
            "order": list(COPY_ORDER),
        }

    def attach_copy(self, path: Path | None) -> bool:
        """Use the sorted native copy at ``path`` for the closest-claims search, if and only if it was built from this dataset with
        this layout. Returns whether it is in use; any doubt means False and the Parquet file is searched as before."""
        if path is None or self.copy_alias is not None or not Path(path).is_file():
            return self.copy_alias is not None
        try:
            probe = duckdb.connect(str(path), read_only=True)
            try:
                stored = {k: json.loads(v) for k, v in probe.execute("SELECT key, value FROM meta").fetchall()}
            finally:
                probe.close()
            if stored != json.loads(json.dumps(self._copy_identity())):
                return False
            with self.lock:
                self.connection.execute(f"ATTACH '{Path(path).as_posix()}' AS fastcopy (READ_ONLY)")
                self.copy_alias = "fastcopy"
            return True
        except (duckdb.Error, OSError, ValueError, KeyError):
            return False

    def warm_copy(self):
        """Read the columns the pool search uses once, so the first investigation after a start does not pay the cold read (4 s)."""
        if self.copy_alias is None:
            return
        try:
            self._run(
                f"SELECT count(*) AS n, max(claim_amount) AS a, max(previous_claims_count) AS p, max(closed_date) AS c, "
                f"min(claim_status) AS s, min(state) AS t, min(claim_id) AS i FROM {self.copy_alias}.claims"
            )
        except duckdb.Error:
            pass

    def close(self):
        with self.lock:
            self.connection.close()
