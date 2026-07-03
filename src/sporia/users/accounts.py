"""Store de comptes SQLite (data/sporia.db) — auth + futur abonnement. Identité = email."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import bcrypt

from sporia.config import settings

# Hash leurre : temps constant quand l'email n'existe pas (anti-énumération).
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt())


def _db_path() -> Path:
    return settings.data_dir / "sporia.db"


def _connect() -> sqlite3.Connection:
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users(
              id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
              name TEXT, role TEXT DEFAULT 'user', email_verified INTEGER DEFAULT 0,
              subscription_status TEXT DEFAULT 'none', stripe_customer_id TEXT,
              current_period_end INTEGER, created_at INTEGER, updated_at INTEGER);
            CREATE TABLE IF NOT EXISTS tokens(
              token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL,
              expires_at INTEGER NOT NULL);
            """
        )


def _norm(email: str) -> str:
    return (email or "").strip().lower()


def create_user(email: str, password: str, name: str | None = None, role: str = "user") -> dict:
    init_db()
    h = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()
    now = int(time.time())
    try:
        with _connect() as c:
            c.execute(
                "INSERT INTO users(email,password_hash,name,role,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?)",
                (_norm(email), h, name, role, now, now),
            )
    except sqlite3.IntegrityError as e:
        raise ValueError("email déjà utilisé") from e
    return get_by_email(email)


def get_by_email(email: str) -> dict | None:
    init_db()
    with _connect() as c:
        r = c.execute("SELECT * FROM users WHERE email=?", (_norm(email),)).fetchone()
    return dict(r) if r else None


def verify_password(email: str, password: str) -> dict | None:
    u = get_by_email(email)
    try:
        if u is None:
            bcrypt.checkpw(password.encode("utf-8"), _DUMMY_HASH)  # temps constant
            return None
        if bcrypt.checkpw(password.encode("utf-8"), u["password_hash"].encode("utf-8")):
            return {"username": u["email"], "name": u["name"] or u["email"], "role": u["role"]}
    except Exception:
        return None
    return None
