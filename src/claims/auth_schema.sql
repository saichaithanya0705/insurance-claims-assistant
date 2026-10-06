CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'admin')),
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS login_limits (
    key TEXT PRIMARY KEY,
    failures INTEGER NOT NULL,
    started_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_audit (
    id INTEGER PRIMARY KEY,
    user_id TEXT,
    kind TEXT NOT NULL,
    time INTEGER NOT NULL
);
