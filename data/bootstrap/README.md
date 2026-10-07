# Portable SQLite databases

`claims.sqlite` includes the 55 saved investigations and their workflow/audit state
from this local workspace (about 15 MiB; refreshed 2026-10-07). It is a consistent SQLite backup, checked
for configured credentials. On a new default checkout, the app copies it into the
working `data/runtime/claims.sqlite` once; existing working databases are preserved.
Legacy cases without an owner are visible only to administrators. Regenerate it with
`uv run python scripts/snapshot_local_databases.py` when another handoff is requested.

`auth.sqlite` is an empty, credential-free schema committed for local setup.
`src/claims/auth_schema.sql` is the canonical schema; regenerate the template with
`uv run python scripts/create_auth_template.py`.

The application initializes its separate working account database next to the
claims database (`data/runtime/auth.sqlite` by default), applying the same schema.
Open the app on localhost to choose the first administrator's username and
password. Use **Accounts** as an administrator to create user or admin credentials.

Working databases, password hashes, sessions and model caches are ignored by Git.
The committed `auth.sqlite` template deliberately contains no usable login credentials.
`.env` is the exception: it is tracked because this is a private repository the owner
syncs between their own machines (see `docs/SETUP.md`).
