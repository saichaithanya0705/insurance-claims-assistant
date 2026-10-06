"""SQLite accounts and revocable sessions; passwords/tokens are never stored raw."""

import hashlib
import secrets
import sqlite3
import time
from pathlib import Path
from threading import RLock
from uuid import uuid4


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode(),
        salt=bytes.fromhex(salt),
        n=131072,
        r=8,
        p=1,
        maxmem=256 * 1024 * 1024,
        dklen=32,
    ).hex()
    return f"scrypt${salt}${digest}"


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(token):
    return hashlib.sha256(("claims-csrf:" + token).encode()).hexdigest()


class AuthStore:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(Path(__file__).with_name("auth_schema.sql").read_text())
        self.connection.commit()
        self.lock = RLock()
        # Equal-cost verification for nonexistent usernames.
        self.dummy_hash = password_hash(secrets.token_urlsafe(24))

    def needs_setup(self):
        with self.lock:
            return self.connection.execute("SELECT count(*) FROM users").fetchone()[0] == 0

    def create_user(self, username, password, role, *, first=False, actor_id=None):
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if first and not self.needs_setup():
                raise ValueError("Initial administrator already exists")
            if first:
                role = "admin"
            user_id = str(uuid4())
            try:
                self.connection.execute(
                    "INSERT INTO users VALUES(?,?,?,?,?)",
                    (user_id, username.casefold(), password_hash(password), role, int(time.time())),
                )
            except sqlite3.IntegrityError:
                raise ValueError("Username already exists") from None
            self.connection.execute(
                "INSERT INTO auth_audit(user_id,kind,time) VALUES(?,?,?)",
                (
                    actor_id or user_id,
                    "initial_admin" if first else f"account_created:{user_id}",
                    int(time.time()),
                ),
            )
            return {"id": user_id, "username": username.casefold(), "role": role}

    def login(self, username, password, client_key):
        with self.lock, self.connection:
            now = int(time.time())
            self.connection.execute("DELETE FROM login_limits WHERE started_at < ?", (now - 900,))
            keys = [
                token_hash("account:" + username.casefold()),
                token_hash("client:" + client_key),
            ]
            for key in keys:
                row = self.connection.execute(
                    "SELECT failures FROM login_limits WHERE key=?", (key,)
                ).fetchone()
                if row and row["failures"] >= 10:
                    raise OverflowError("Too many sign-in attempts. Try again in 15 minutes.")
            user = self.connection.execute(
                "SELECT * FROM users WHERE username=?", (username.casefold(),)
            ).fetchone()
            stored = user["password_hash"] if user else self.dummy_hash
            try:
                _, salt, _ = stored.split("$")
                valid = secrets.compare_digest(password_hash(password, salt), stored)
            except ValueError:
                valid = False
            if not user or not valid:
                for key in keys:
                    self.connection.execute(
                        "INSERT INTO login_limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET failures=failures+1",
                        (key, now),
                    )
                self.connection.execute(
                    "INSERT INTO auth_audit(kind,time) VALUES('login_failed',?)", (now,)
                )
                return None
            self.connection.execute("DELETE FROM login_limits WHERE key=?", (keys[0],))
            self.connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            token = secrets.token_urlsafe(32)
            self.connection.execute(
                "INSERT INTO sessions VALUES(?,?,?)", (token_hash(token), user["id"], now + 43200)
            )
            self.connection.execute(
                "INSERT INTO auth_audit(user_id,kind,time) VALUES(?,'login',?)", (user["id"], now)
            )
            return token, {key: user[key] for key in ("id", "username", "role")}

    def actor(self, token):
        if not token:
            return None
        with self.lock:
            row = self.connection.execute(
                "SELECT u.id,u.username,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?",
                (token_hash(token), int(time.time())),
            ).fetchone()
            return dict(row) if row else None

    def logout(self, token):
        with self.lock, self.connection:
            self.connection.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))

    def users(self):
        with self.lock:
            return [
                dict(row)
                for row in self.connection.execute(
                    "SELECT id,username,role,created_at FROM users ORDER BY created_at,id"
                )
            ]

    def close(self):
        self.connection.close()
