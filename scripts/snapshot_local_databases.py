"""Export portable saved-case SQLite state for the requested Git handoff.

SQLite backup captures WAL contents consistently. The authentication snapshot is
schema-only: login accounts and sessions remain specific to the local machine.
"""

import sqlite3
from pathlib import Path

from claims.core.settings import Settings

settings = Settings()
root = Path(__file__).resolve().parents[1]
source_path = settings.claims_database_path.resolve()
target = root / "data/bootstrap/claims.sqlite"
target.parent.mkdir(parents=True, exist_ok=True)
with (
    sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True) as source,
    sqlite3.connect(target) as destination,
):
    source.backup(destination)
    destination.execute("PRAGMA journal_mode=DELETE")
    destination.execute("VACUUM")
    assert destination.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
# Verify configured credentials did not enter the exported saved-case database.
raw = target.read_bytes()
for value in (
    settings.synapt_password,
    settings.llm_api_key,
    settings.nvidia_api_key,
    settings.claims_api_key,
):
    secret = value.get_secret_value()
    if secret and secret.encode() in raw:
        raise RuntimeError("Configured credentials found in database snapshot; do not commit")
with sqlite3.connect(target) as connection:
    count = connection.execute("SELECT count(*) FROM investigations").fetchone()[0]
print(f"Portable saved-case snapshot: {count} investigations, {target.stat().st_size} bytes")
