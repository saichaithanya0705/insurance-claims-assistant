"""Create a credential-free SQLite schema suitable for version control."""

import sqlite3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / "data/bootstrap/auth.sqlite"
target.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(target) as connection:
    connection.executescript((root / "src/claims/api/auth_schema.sql").read_text())
    for table in ("users", "sessions", "login_limits", "auth_audit"):
        if connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]:
            raise RuntimeError("Bootstrap database must not contain accounts or sessions")
print("Credential-free SQLite bootstrap schema ready")
