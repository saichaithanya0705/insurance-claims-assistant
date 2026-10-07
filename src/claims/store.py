import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

STATE_NAMES = json.loads(Path(__file__).with_name("us_states.json").read_text(encoding="utf-8"))



def _short_title(text: str, limit: int = 90) -> str:
    """First words of a description, cut at a word boundary rather than mid-word."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[: limit + 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{cut or text[:limit]}…"

class Store:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        template = Path("data/bootstrap/claims.sqlite")
        if (
            not path.exists()
            and path.resolve() == Path("data/runtime/claims.sqlite").resolve()
            and template.exists()
        ):
            # Seed only the default workspace; custom/test databases stay isolated.
            shutil.copyfile(template, path)
        self.connection = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.lock = RLock()
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS investigations(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, run_id TEXT, time TEXT, kind TEXT, body TEXT);
            CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY, run_id TEXT, rating INTEGER, note TEXT, reviewed INTEGER, time TEXT);
        """)
        self.connection.commit()
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(investigations)")}
        if "owner_id" not in columns:
            self.connection.execute("ALTER TABLE investigations ADD COLUMN owner_id TEXT")
            self.connection.commit()
        feedback_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(feedback)")}
        for column, ddl in (
            ("promoted", "INTEGER NOT NULL DEFAULT 0"),
            ("promoted_at", "TEXT"),
            ("promotion_ref", "TEXT"),
            ("promoted_by", "TEXT"),
        ):
            if column not in feedback_columns:
                self.connection.execute(f"ALTER TABLE feedback ADD COLUMN {column} {ddl}")
        self.connection.commit()

    def save(self, run_id, body):
        with self.lock, self.connection:
            # The independent judge finishes in the background. A later save of workflow state that
            # still says "pending" must not erase a verdict that arrived in the meantime.
            if (body.get("judge") or {}).get("status") == "pending":
                row = self.connection.execute(
                    "SELECT json_extract(body, '$.judge') FROM investigations WHERE id=?", (run_id,)
                ).fetchone()
                finished = json.loads(row[0]) if row and row[0] else None
                if finished and finished.get("status") in ("completed", "failed"):
                    body = body | {"judge": finished}
            self.connection.execute(
                "INSERT INTO investigations(id,body) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                (run_id, json.dumps(body)),
            )

    def set_judge(self, run_id, verdict):
        """Attach the independent judge's verdict to a saved run; False if the run is gone."""
        with self.lock, self.connection:
            row = self.connection.execute(
                "SELECT body FROM investigations WHERE id=?", (run_id,)
            ).fetchone()
            if row is None:
                return False
            body = json.loads(row[0]) | {"judge": verdict}
            self.connection.execute(
                "UPDATE investigations SET body=? WHERE id=?", (json.dumps(body), run_id)
            )
            return True

    def get(self, run_id):
        with self.lock:
            row = self.connection.execute(
                "SELECT body FROM investigations WHERE id=?", (run_id,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def search(
        self,
        *,
        q="",
        status="",
        claim_type="",
        state="",
        date_from="",
        date_to="",
        min_amount=None,
        max_amount=None,
        offset=0,
        limit=20,
        owner_id=None,
        sort="recent",
        tier="",
        open_only=False,
    ):
        """Search saved investigations, never the historical comparison corpus.

        Bound SQL parameters and instr preserve literal queries (including %/_).
        Legacy records need no migration: metadata comes from their saved snapshot.
        """
        clauses, params = [], []
        if owner_id is not None:
            clauses.append("owner_id = ?")
            params.append(owner_id)
        for term in q.strip().lower().split():
            clauses.append(
                "instr(lower(id || ' ' || coalesce(json_extract(body, '$.title'), '') || ' ' || coalesce(json_extract(body, '$.claim.description'), '') || ' ' || coalesce(json_extract(body, '$.claim.claim_type'), '') || ' ' || coalesce(json_extract(body, '$.claim.state'), '') || ' ' || coalesce((SELECT value FROM json_each(?) WHERE key = json_extract(body, '$.claim.state')), '')), ?) > 0"
            )
            params.extend([json.dumps(STATE_NAMES), term])
        for value, field in [
            (status, "status"),
            (claim_type, "claim.claim_type"),
            (state.upper(), "claim.state"),
        ]:
            if value:
                clauses.append(f"json_extract(body, '$.{field}') = ?")
                params.append(value)
        if tier:
            clauses.append("json_extract(body, '$.priority.tier') = ?")
            params.append(tier)
        if open_only:
            clauses.append(
                "json_extract(body, '$.status') IN ('awaiting_review', 'needs_manual_review')"
            )
        for value, operator in [(date_from, ">="), (date_to, "<=")]:
            if value:
                clauses.append(f"json_extract(body, '$.claim.claim_filed_date') {operator} ?")
                params.append(value)
        for value, operator in [(min_amount, ">="), (max_amount, "<=")]:
            if value is not None:
                clauses.append(f"json_extract(body, '$.claim.claim_amount') {operator} ?")
                params.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.lock:
            total = self.connection.execute(
                "SELECT count(*) FROM investigations" + where, params
            ).fetchone()[0]
            rows = self.connection.execute(
                "SELECT id, body FROM investigations"
                + where
                + (
                    " ORDER BY coalesce(json_extract(body, '$.priority.score'), -1) DESC, rowid DESC"
                    if sort == "priority"
                    else " ORDER BY rowid DESC"
                )
                + " LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        items = []
        for row in rows:
            run = json.loads(row["body"])
            claim = run.get("claim", {})
            description = claim.get("description", "")
            position = max(0, description.lower().find(q.strip().lower()) - 40) if q.strip() else 0
            items.append(
                {
                    "run_id": row["id"],
                    "title": run.get("title") or _short_title(description),
                    "description": description[position : position + 220],
                    "status": run.get("status", "unknown"),
                    "claim_type": claim.get("claim_type"),
                    "state": claim.get("state", ""),
                    "claim_amount": claim.get("claim_amount", 0),
                    "claim_filed_date": claim.get("claim_filed_date", ""),
                    "priority_score": (run.get("priority") or {}).get("score"),
                    "priority_tier": (run.get("priority") or {}).get("tier"),
                }
            )
        return {"items": items, "total": total, "offset": offset, "limit": limit}

    def event(self, run_id, kind, body):
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO audit(run_id,time,kind,body) VALUES(?,?,?,?)",
                (run_id, datetime.now(UTC).isoformat(), kind, json.dumps(body)),
            )

    def search_documents(self, owner_id=None):
        """Small saved-case catalog projection; no evidence, prompts or traces."""
        with self.lock:
            rows = self.connection.execute(
                "SELECT id, json_extract(body, '$.title') AS title, "
                "json_extract(body, '$.status') AS status, "
                "json_extract(body, '$.claim') AS claim "
                "FROM investigations"
                + (" WHERE owner_id=?" if owner_id is not None else "")
                + " ORDER BY rowid DESC",
                [owner_id] if owner_id is not None else [],
            ).fetchall()
        items = []
        for row in rows:
            claim = json.loads(row["claim"] or "{}")
            description = claim.get("description", "")
            items.append(
                {
                    "run_id": row["id"],
                    "title": row["title"] or description[:90] or "Untitled claim",
                    "description": description,
                    "status": row["status"] or "unknown",
                    "claim_type": claim.get("claim_type"),
                    "state": claim.get("state", ""),
                    "claim_amount": claim.get("claim_amount", 0),
                    "claim_filed_date": claim.get("claim_filed_date", ""),
                }
            )
        return items

    def set_owner(self, run_id, owner_id):
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE investigations SET owner_id=? WHERE id=?", (owner_id, run_id)
            )

    def can_access(self, run_id, owner_id):
        with self.lock:
            return (
                self.connection.execute(
                    "SELECT 1 FROM investigations WHERE id=? AND owner_id=?", (run_id, owner_id)
                ).fetchone()
                is not None
            )

    def add_feedback(self, run_id, rating, note):
        with self.lock, self.connection:
            reviewed = self.get(run_id).get("status") == "reviewed"
            cursor = self.connection.execute(
                "INSERT INTO feedback(run_id,rating,note,reviewed,time) VALUES(?,?,?,?,?)",
                (run_id, rating, note, int(reviewed), datetime.now(UTC).isoformat()),
            )
            return {"id": cursor.lastrowid, "reviewed": reviewed, "published_to_synapt": False}

    def audit_records(self, run_id, offset=0, limit=100):
        with self.lock:
            total = self.connection.execute(
                "SELECT count(*) FROM audit WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            rows = self.connection.execute(
                "SELECT id,time,kind,body FROM audit WHERE run_id=? ORDER BY id LIMIT ? OFFSET ?",
                (run_id, limit, offset),
            ).fetchall()
        return {
            "items": [dict(row, body=json.loads(row["body"])) for row in rows],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    def lessons(self):
        with self.lock:
            rows = self.connection.execute(
                "SELECT f.id, f.run_id, f.rating, f.note, f.promoted, f.promoted_at, f.promotion_ref, "
                "json_extract(i.body, '$.claim.claim_type') AS claim_type, "
                "json_extract(i.body, '$.claim.state') AS state "
                "FROM feedback f LEFT JOIN investigations i ON i.id = f.run_id "
                "WHERE f.reviewed=1 ORDER BY f.id DESC LIMIT 100"
            ).fetchall()
            return [dict(row) | {"promoted": bool(row["promoted"])} for row in rows]

    def lesson(self, lesson_id):
        with self.lock:
            row = self.connection.execute(
                "SELECT id, run_id, rating, note, reviewed, promoted FROM feedback WHERE id=?",
                (lesson_id,),
            ).fetchone()
            return dict(row) if row else None

    def mark_promoted(self, lesson_id, reference, actor):
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE feedback SET promoted=1, promoted_at=?, promotion_ref=?, promoted_by=? WHERE id=?",
                (datetime.now(UTC).isoformat(), reference, actor, lesson_id),
            )

    def promoted_lessons(self, claim_type, limit=3):
        """Reviewed lessons that an administrator approved for reuse, newest first."""
        with self.lock:
            rows = self.connection.execute(
                "SELECT f.id, f.run_id, f.rating, f.note, "
                "json_extract(i.body, '$.claim.claim_type') AS claim_type, "
                "json_extract(i.body, '$.claim.state') AS state "
                "FROM feedback f JOIN investigations i ON i.id = f.run_id "
                "WHERE f.promoted=1 AND f.reviewed=1 "
                "AND (json_extract(i.body, '$.claim.claim_type') = ? OR ? IS NULL) "
                "ORDER BY f.id DESC LIMIT ?",
                (claim_type, claim_type, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def close(self):
        self.connection.close()
