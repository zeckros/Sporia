# Sporia — Comptes & auto-inscription (chantier 4.1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer les comptes statiques `config.yaml` par un store SQLite dynamique avec auto-inscription, reset de mot de passe (email transactionnel) et un schéma prêt pour l'abonnement — sans casser la prod.

**Architecture:** Un store SQLite (`sporia/users/accounts.py`) devient la source des comptes ; l'auth (`sporia/web/auth.py`) lit ce store ; l'email transactionnel (`sporia/email.py`, Brevo) sert la vérification/reset ; de nouvelles routes gèrent inscription/reset ; un script migre `config.yaml` + remappe prefs/spots.

**Tech Stack:** stdlib `sqlite3`, bcrypt, FastAPI/Starlette, requests (Brevo), pytest.

## Global Constraints

- **Branche** `chantier-comptes` (déjà créée).
- **Identité = email** (login par email). Rôle porté par la session (`user["role"]`).
- **Vérification email NON bloquante** (compte utilisable dès l'inscription).
- **Email** : Brevo via env `BREVO_API_KEY` + `MAIL_FROM` ; sans clé → **no-op + log** (pas d'échec dur en DEV).
- **NON déployé seul** : mergé sur `main` mais poussé/déployé seulement avec 4.2 (paiement) + 4.3 (gating). La prod reste sur invitation d'ici là.
- **Store SQLite** dans `data/sporia.db` (gitignoré). Connexions courtes par opération.
- Commits fréquents, messages sans `Co-Authored-By`. `venv/Scripts/python.exe`.

## File Structure

- `src/sporia/users/accounts.py` — store SQLite (users + tokens).
- `src/sporia/email.py` — abstraction d'envoi transactionnel.
- `src/sporia/web/auth.py` — `verify` sur le store, `require_admin` via rôle de session.
- `src/sporia/web/app.py` — routes register / password-forgot / password-reset / verify-email ; login via store.
- `scripts/migrate_accounts.py` — seed depuis config.yaml + remap prefs/spots.
- `web/index.html`, `web/app.js` — formulaire inscription + « mot de passe oublié ».
- Tests : `tests/test_accounts.py`, `tests/test_email.py`, `tests/test_register_flow.py`.

---

### Task 1: Store SQLite — comptes (users)

**Files:**
- Create: `src/sporia/users/accounts.py`
- Test: `tests/test_accounts.py`

**Interfaces:**
- Produces: `init_db()` ; `create_user(email, password, name=None, role="user") -> dict` (ValueError si email pris) ; `get_by_email(email) -> dict | None` ; `verify_password(email, password) -> dict | None` (renvoie `{username: email, name, role}` ou None) ; `_db_path() -> Path` (monkeypatchable).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_accounts.py`:
```python
"""Store de comptes SQLite."""

from __future__ import annotations

import pytest

from sporia.users import accounts


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "_db_path", lambda: tmp_path / "t.db")


def test_create_and_get():
    u = accounts.create_user("A@Ex.com", "secret123", name="Al")
    assert u["email"] == "a@ex.com"  # normalisé lower
    assert accounts.get_by_email("a@ex.com")["name"] == "Al"


def test_duplicate_email_raises():
    accounts.create_user("a@ex.com", "secret123")
    with pytest.raises(ValueError):
        accounts.create_user("a@ex.com", "other123")


def test_verify_password():
    accounts.create_user("a@ex.com", "secret123", name="Al", role="admin")
    assert accounts.verify_password("a@ex.com", "wrong") is None
    assert accounts.verify_password("nobody@ex.com", "secret123") is None
    ok = accounts.verify_password("a@ex.com", "secret123")
    assert ok == {"username": "a@ex.com", "name": "Al", "role": "admin"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_accounts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sporia.users.accounts'`.

- [ ] **Step 3: Implement `src/sporia/users/accounts.py`**

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_accounts.py -q`
Expected: 3 passed.

- [ ] **Step 5: Lint + commit**

```bash
venv/Scripts/python.exe -m ruff check src/sporia/users/accounts.py tests/test_accounts.py
git add src/sporia/users/accounts.py tests/test_accounts.py
git commit -m "feat: SQLite account store (users, create/get/verify)"
```

---

### Task 2: Store — mot de passe & tokens

**Files:**
- Modify: `src/sporia/users/accounts.py`
- Modify: `tests/test_accounts.py`

**Interfaces:**
- Produces: `set_password(user_id, password)` ; `set_verified(user_id)` ; `create_token(user_id, kind, ttl_s=3600) -> str` ; `consume_token(token, kind) -> int | None` (usage unique + expiration).

- [ ] **Step 1: Append the failing tests** to `tests/test_accounts.py`:
```python
def test_token_roundtrip_single_use():
    u = accounts.create_user("a@ex.com", "secret123")
    tok = accounts.create_token(u["id"], "reset", ttl_s=60)
    assert accounts.consume_token(tok, "reset") == u["id"]
    assert accounts.consume_token(tok, "reset") is None  # usage unique


def test_token_expired():
    u = accounts.create_user("a@ex.com", "secret123")
    tok = accounts.create_token(u["id"], "verify", ttl_s=-1)  # déjà expiré
    assert accounts.consume_token(tok, "verify") is None


def test_set_password_and_verified():
    u = accounts.create_user("a@ex.com", "secret123")
    accounts.set_password(u["id"], "newpass123")
    assert accounts.verify_password("a@ex.com", "newpass123") is not None
    accounts.set_verified(u["id"])
    assert accounts.get_by_email("a@ex.com")["email_verified"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_accounts.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'create_token'`.

- [ ] **Step 3: Append to `src/sporia/users/accounts.py`**
```python
import secrets  # (ajouter en tête avec les autres imports)


def set_password(user_id: int, password: str) -> None:
    h = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()
    with _connect() as c:
        c.execute(
            "UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
            (h, int(time.time()), user_id),
        )


def set_verified(user_id: int) -> None:
    with _connect() as c:
        c.execute(
            "UPDATE users SET email_verified=1, updated_at=? WHERE id=?",
            (int(time.time()), user_id),
        )


def create_token(user_id: int, kind: str, ttl_s: int = 3600) -> str:
    tok = secrets.token_urlsafe(32)
    with _connect() as c:
        c.execute(
            "INSERT INTO tokens(token,user_id,kind,expires_at) VALUES(?,?,?,?)",
            (tok, user_id, kind, int(time.time()) + ttl_s),
        )
    return tok


def consume_token(token: str, kind: str) -> int | None:
    with _connect() as c:
        r = c.execute(
            "SELECT user_id, expires_at FROM tokens WHERE token=? AND kind=?", (token, kind)
        ).fetchone()
        if r is None:
            return None
        c.execute("DELETE FROM tokens WHERE token=?", (token,))  # usage unique
    return r["user_id"] if r["expires_at"] >= int(time.time()) else None
```

- [ ] **Step 4: Run + lint + commit**

Run: `venv/Scripts/python.exe -m pytest tests/test_accounts.py -q` → 6 passed ; `venv/Scripts/python.exe -m ruff check src/sporia/users/accounts.py`.
```bash
git add src/sporia/users/accounts.py tests/test_accounts.py
git commit -m "feat: account store password reset + single-use tokens"
```

---

### Task 3: Envoi d'email transactionnel

**Files:**
- Create: `src/sporia/email.py`
- Test: `tests/test_email.py`

**Interfaces:**
- Produces: `send_email(to, subject, html) -> bool` (True si envoyé ; False si pas de clé ou échec).

- [ ] **Step 1: Write the failing test** `tests/test_email.py`:
```python
"""Abstraction d'envoi d'email (no-op sans clé)."""

from __future__ import annotations

from sporia.email import send_email


def test_noop_without_key(monkeypatch, capsys):
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    assert send_email("a@ex.com", "Hi", "<p>x</p>") is False
    assert "would send" in capsys.readouterr().out


def test_sends_with_key(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "k")
    calls = {}

    class R:
        status_code = 201

    def fake_post(url, **kw):
        calls["url"] = url
        calls["json"] = kw.get("json")
        return R()

    import sporia.email as em

    monkeypatch.setattr(em.requests, "post", fake_post)
    assert send_email("a@ex.com", "Hi", "<p>x</p>") is True
    assert "brevo.com" in calls["url"]
    assert calls["json"]["to"] == [{"email": "a@ex.com"}]
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_email.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sporia.email'`.

- [ ] **Step 3: Implement `src/sporia/email.py`**
```python
"""Envoi d'email transactionnel (Brevo). No-op + log si BREVO_API_KEY absent (DEV)."""

from __future__ import annotations

import os

import requests


def send_email(to: str, subject: str, html: str) -> bool:
    key = os.environ.get("BREVO_API_KEY")
    sender = os.environ.get("MAIL_FROM", "no-reply@sporia.duckdns.org")
    if not key:
        print(f"[email] (pas de BREVO_API_KEY) enverrait à {to} : {subject}  # would send")
        return False
    try:
        r = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": key, "content-type": "application/json"},
            json={
                "sender": {"email": sender, "name": "Sporia"},
                "to": [{"email": to}],
                "subject": subject,
                "htmlContent": html,
            },
            timeout=15,
        )
        return r.status_code < 300
    except Exception as e:  # réseau/Brevo down → on ne casse pas la requête utilisateur
        print(f"[email] échec envoi à {to} : {e}")
        return False
```

- [ ] **Step 4: Run + lint + commit**

Run: `venv/Scripts/python.exe -m pytest tests/test_email.py -q` → 2 passed ; ruff check.
```bash
git add src/sporia/email.py tests/test_email.py
git commit -m "feat: transactional email (Brevo) with dev no-op"
```

---

### Task 4: Auth sur le store (verify + require_admin par rôle)

**Files:**
- Modify: `src/sporia/web/auth.py`, `tests/test_auth.py`, `tests/test_admin.py`

**Interfaces:**
- Consumes: `accounts.verify_password` (Task 1).
- Produces: `verify(email, password) -> dict | None` (via store) ; `require_admin` gate sur `user["role"]`.

- [ ] **Step 1: Rewrite `verify` + `require_admin` in `src/sporia/web/auth.py`**

Replace the body of `verify` with a call to the store, and `require_admin` with a session-role check:
```python
from sporia.users import accounts  # (ajouter en tête)


def verify(email: str, password: str) -> dict | None:
    """Vérifie l'email+mot de passe via le store SQLite. Renvoie {username,name,role} ou None."""
    return accounts.verify_password(email, password)


def require_admin(request: Request) -> dict:
    """Comme require_user, mais restreint aux comptes role=admin (rôle porté par la session)."""
    user = require_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Réservé à l'administrateur.")
    return user
```
Keep `require_user` unchanged. `load_config`/`admin_usernames`/`_DUMMY_HASH` peuvent rester (utilisés par la migration / compat) ou être retirés s'ils deviennent inutilisés — vérifier avec `grep`.

- [ ] **Step 2: Ensure login puts `role` in session**

In `src/sporia/web/app.py`, the login route already stores `request.session["user"] = user` where `user` = `verify(...)` output. Since `verify` now returns `{username,name,role}`, the role is in the session automatically. **No change needed** beyond confirming `verify` output includes `role` (it does).

- [ ] **Step 3: Update `tests/test_auth.py` + `tests/test_admin.py` to seed a store account**

`test_auth.py` : `verify("dev", "wrong-password")` used config.yaml. Replace with a fixture that seeds the store, then asserts on the store. Add near the top of `tests/test_auth.py`:
```python
import pytest

from sporia.users import accounts


@pytest.fixture(autouse=True)
def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "_db_path", lambda: tmp_path / "t.db")
    accounts.create_user("dev@ex.com", "devpass123", name="Dev", role="user")
```
And change the two verify tests to:
```python
def test_verify_unknown_user_returns_none():
    assert verify("no-such@ex.com", "whatever") is None


def test_verify_wrong_password_returns_none():
    assert verify("dev@ex.com", "wrong-password") is None
```
`test_admin.py` : `test_admin_usernames_reads_role` teste `admin_usernames` (config.yaml). Le remplacer par un test du gate par rôle :
```python
def test_require_admin_checks_session_role():
    from sporia.web.auth import require_admin
    from fastapi import HTTPException

    class Req:
        session = {"user": {"username": "u@ex.com", "name": "U", "role": "user"}}

    with pytest.raises(HTTPException):
        require_admin(Req())
```

- [ ] **Step 4: Run + lint + commit**

Run: `venv/Scripts/python.exe -m pytest tests/test_auth.py tests/test_admin.py -q` → tous verts ; ruff check src tests.
```bash
git add src/sporia/web/auth.py tests/test_auth.py tests/test_admin.py
git commit -m "feat: auth reads SQLite store; require_admin via session role"
```

---

### Task 5: Routes inscription / reset / vérification

**Files:**
- Modify: `src/sporia/web/app.py`
- Test: `tests/test_register_flow.py`

**Interfaces:**
- Consumes: `accounts.*` (Tasks 1-2), `sporia.email.send_email` (Task 3), `verify` (Task 4).

- [ ] **Step 1: Write the failing test** `tests/test_register_flow.py`:
```python
"""Inscription / reset via TestClient (email mocké)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from sporia.users import accounts
from sporia.web.app import app


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "_db_path", lambda: tmp_path / "t.db")
    import sporia.web.app as appmod

    monkeypatch.setattr(appmod, "send_email", lambda *a, **k: True)


def test_register_then_authenticated():
    c = TestClient(app)
    r = c.post("/api/register", json={"email": "n@ex.com", "password": "secret123", "name": "N"})
    assert r.status_code == 200
    assert c.get("/api/me").json()["authenticated"] is True


def test_register_duplicate_409():
    c = TestClient(app)
    c.post("/api/register", json={"email": "n@ex.com", "password": "secret123"})
    c2 = TestClient(app)
    r = c2.post("/api/register", json={"email": "n@ex.com", "password": "other123"})
    assert r.status_code == 409


def test_forgot_is_neutral_200_even_unknown():
    c = TestClient(app)
    assert c.post("/api/password/forgot", json={"email": "ghost@ex.com"}).status_code == 200


def test_reset_changes_password():
    accounts.create_user("r@ex.com", "old12345")
    uid = accounts.get_by_email("r@ex.com")["id"]
    tok = accounts.create_token(uid, "reset", 600)
    c = TestClient(app)
    assert c.post("/api/password/reset", json={"token": tok, "password": "new12345"}).status_code == 200
    assert accounts.verify_password("r@ex.com", "new12345") is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_register_flow.py -q`
Expected: FAIL — `/api/register` renvoie 404 (route absente).

- [ ] **Step 3: Add the routes in `src/sporia/web/app.py`**

Add the import near the top: `from sporia.email import send_email` and `from sporia.users import accounts`. Add the models + routes near the login route:
```python
class RegisterIn(BaseModel):
    email: str
    password: str
    name: str | None = None


class ForgotIn(BaseModel):
    email: str


class ResetIn(BaseModel):
    token: str
    password: str


def _valid_email(e: str) -> str:
    if not _EMAIL_RE.match(e or "") or len(e) > 120:
        raise HTTPException(status_code=400, detail="Email invalide.")
    return e.strip().lower()


@app.post("/api/register")
def register(body: RegisterIn, request: Request):
    email = _valid_email(body.email)
    if len(body.password or "") < 8:
        raise HTTPException(status_code=400, detail="Mot de passe trop court (min 8).")
    try:
        accounts.create_user(email, body.password, name=(body.name or "").strip() or None)
    except ValueError:
        raise HTTPException(status_code=409, detail="Un compte existe déjà pour cet email.") from None
    tok = accounts.create_token(accounts.get_by_email(email)["id"], "verify", 7 * 24 * 3600)
    base = str(request.base_url).rstrip("/")
    send_email(email, "Bienvenue sur Sporia — vérifiez votre email",
               f'<p>Bienvenue ! Confirmez votre email : <a href="{base}/api/verify-email?token={tok}">vérifier</a></p>')
    user = verify(email, body.password)
    request.session["user"] = user
    return {"ok": True, "name": user["name"]}


@app.post("/api/password/forgot")
def password_forgot(body: ForgotIn, request: Request):
    u = accounts.get_by_email((body.email or "").strip().lower())
    if u:  # réponse toujours 200 neutre (anti-énumération)
        tok = accounts.create_token(u["id"], "reset", 3600)
        base = str(request.base_url).rstrip("/")
        send_email(u["email"], "Sporia — réinitialisation du mot de passe",
                   f'<p>Réinitialisez : <a href="{base}/?reset={tok}">nouveau mot de passe</a> (valide 1h)</p>')
    return {"ok": True}


@app.post("/api/password/reset")
def password_reset(body: ResetIn):
    if len(body.password or "") < 8:
        raise HTTPException(status_code=400, detail="Mot de passe trop court (min 8).")
    uid = accounts.consume_token(body.token, "reset")
    if uid is None:
        raise HTTPException(status_code=400, detail="Lien invalide ou expiré.")
    accounts.set_password(uid, body.password)
    return {"ok": True}


@app.get("/api/verify-email")
def verify_email(token: str):
    uid = accounts.consume_token(token, "verify")
    if uid is not None:
        accounts.set_verified(uid)
    return FileResponse(str(settings.web_dir / "index.html"),
                        headers={"Cache-Control": "no-cache"})
```

- [ ] **Step 4: Run to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_register_flow.py -q`
Expected: 4 passed.

- [ ] **Step 5: Lint + full suite + commit**

Run: `venv/Scripts/python.exe -m ruff check src tests` ; `venv/Scripts/python.exe -m pytest -q -m "not slow"`.
```bash
git add src/sporia/web/app.py tests/test_register_flow.py
git commit -m "feat: register / password-forgot / password-reset / verify-email routes"
```

---

### Task 6: Migration `config.yaml` → SQLite + remap prefs/spots

**Files:**
- Create: `scripts/migrate_accounts.py`

- [ ] **Step 1: Implement the idempotent migration**
```python
#!/usr/bin/env python3
"""Migre les comptes config.yaml → SQLite (si users vide) + remappe user_prefs/user_spots
(clé username → email). Idempotent : relançable sans dupliquer."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import yaml  # noqa: E402

from sporia.config import settings  # noqa: E402
from sporia.users import accounts  # noqa: E402


def _remap(json_path: Path, mapping: dict[str, str]) -> None:
    if not json_path.exists():
        return
    data = json.loads(json_path.read_text(encoding="utf-8"))
    changed = False
    for old, new in mapping.items():
        if old in data and new not in data:
            data[new] = data.pop(old)
            changed = True
    if changed:
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  remap {json_path.name}: {mapping}")


def main() -> None:
    accounts.init_db()
    with accounts._connect() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    if n > 0:
        print(f"users déjà peuplé ({n}) — migration ignorée.")
        return
    cfg = yaml.safe_load((settings.base_dir / "config.yaml").read_text(encoding="utf-8")) or {}
    users = cfg.get("credentials", {}).get("usernames", {})
    mapping = {}
    for username, v in users.items():
        email = (v.get("email") or f"{username}@sporia.local").strip().lower()
        # insertion directe du hash bcrypt existant (pas de re-hash) :
        import time as _t

        with accounts._connect() as c:
            c.execute(
                "INSERT INTO users(email,password_hash,name,role,email_verified,created_at,updated_at)"
                " VALUES(?,?,?,?,1,?,?)",
                (email, v["password"], v.get("name", username), v.get("role", "user"),
                 int(_t.time()), int(_t.time())),
            )
        mapping[username] = email
        print(f"  + {username} → {email} ({v.get('role','user')})")
    _remap(settings.data_dir / "user_prefs.json", mapping)
    _remap(settings.data_dir / "user_spots.json", mapping)
    print("Migration terminée.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test idempotence locally (against a scratch DB)**

Run:
```bash
SPORIA_TEST=1 venv/Scripts/python.exe -c "import sys; sys.argv=['x']; from sporia.users import accounts; import tempfile,os; d=tempfile.mkdtemp(); accounts._db_path=lambda: __import__('pathlib').Path(d)/'t.db'; import runpy; runpy.run_path('scripts/migrate_accounts.py', run_name='__main__'); runpy.run_path('scripts/migrate_accounts.py', run_name='__main__')"
```
Expected: 1er run migre les comptes de `config.yaml` ; 2e run affiche « users déjà peuplé — migration ignorée » (pas de doublon). *(Si le monkeypatch inline est fragile, valider plutôt via un test dédié : créer 1 user puis vérifier que `main()` affiche « ignorée ».)*

- [ ] **Step 3: Document + commit**

Add to `ORACLE_DEPLOY.md` (section redéploiement 4.x) : « À la mise en vente : `sudo -u app ./venv/bin/python scripts/migrate_accounts.py` une fois (idempotent) — bascule les comptes vers SQLite. »
```bash
git add scripts/migrate_accounts.py ORACLE_DEPLOY.md
git commit -m "feat: idempotent config.yaml -> SQLite account migration + prefs/spots remap"
```

---

### Task 7: Frontend — inscription + mot de passe oublié

**Files:**
- Modify: `web/index.html`, `web/app.js`

**Interfaces:**
- Consumes: routes `/api/register`, `/api/password/forgot`, `/api/password/reset` (Task 5).

- [ ] **Step 1: Add a signup form on the landing**

In `web/index.html`, dans la section « DEMANDE D'ACCÈS / CONTACT » (autour de `id="access-form"`), ajouter un formulaire d'inscription (garder l'existant ou le remplacer) :
```html
<form id="register-form" class="mt-6 bg-white rounded-2xl shadow-card border border-slate-200 p-5 sm:p-6 space-y-4">
  <input id="reg-name" type="text" placeholder="Nom (optionnel)" class="w-full rounded-xl border border-slate-300 px-4 py-2">
  <input id="reg-email" type="email" required placeholder="Email" autocomplete="email" class="w-full rounded-xl border border-slate-300 px-4 py-2">
  <input id="reg-pass" type="password" required minlength="8" placeholder="Mot de passe (min 8)" autocomplete="new-password" class="w-full rounded-xl border border-slate-300 px-4 py-2">
  <p id="reg-msg" class="hidden text-sm font-semibold"></p>
  <button type="submit" class="w-full px-4 py-2 rounded-xl bg-brand-500 hover:bg-brand-600 text-white font-semibold">Créer mon compte</button>
</form>
```
Et sur l'écran de connexion (`id="login-form"`), ajouter sous le bouton : `<button type="button" id="forgot-link" class="text-sm text-slate-500 hover:text-brand-600 mt-2">Mot de passe oublié ?</button>`

- [ ] **Step 2: Wire the JS in `web/app.js`**

Ajouter (près du handler d'accès existant, `~ligne 137`) :
```javascript
// Inscription (landing) → POST /api/register → bascule dans l'app
document.getElementById("register-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = document.getElementById("reg-msg");
  try {
    await API.post("/api/register", {
      email: document.getElementById("reg-email").value.trim(),
      password: document.getElementById("reg-pass").value,
      name: document.getElementById("reg-name").value.trim(),
    });
    location.reload(); // session posée → l'app s'affiche
  } catch (err) {
    msg.textContent = err.status === 409 ? "Un compte existe déjà pour cet email." : "Inscription impossible.";
    msg.classList.remove("hidden"); msg.classList.add("text-red-600");
  }
});

// Mot de passe oublié → POST /api/password/forgot (réponse neutre)
document.getElementById("forgot-link")?.addEventListener("click", async () => {
  const email = prompt("Votre email pour réinitialiser le mot de passe :");
  if (!email) return;
  await API.post("/api/password/forgot", { email: email.trim() });
  alert("Si un compte existe, un email de réinitialisation a été envoyé.");
});

// Lien de reset (?reset=TOKEN dans l'URL) → demande un nouveau mot de passe
(async () => {
  const tok = new URLSearchParams(location.search).get("reset");
  if (!tok) return;
  const pw = prompt("Nouveau mot de passe (min 8) :");
  if (!pw) return;
  try {
    await API.post("/api/password/reset", { token: tok, password: pw });
    alert("Mot de passe modifié. Connectez-vous.");
    location.href = "/";
  } catch { alert("Lien invalide ou expiré."); }
})();
```
(Adapter aux helpers existants : `API.post` renvoie/juge le statut comme le fait déjà `access-form`.)

- [ ] **Step 3: Manual verification**

Run: `venv/Scripts/python.exe -m uvicorn sporia.web.app:app --port 8000` (DEV : email = no-op log).
- Ouvrir `/`, créer un compte via le formulaire → l'app s'affiche, `/api/me` authentifié.
- « Mot de passe oublié » → voir dans les logs `[email] (pas de BREVO_API_KEY) enverrait à …`.

- [ ] **Step 4: Commit**

```bash
git add web/index.html web/app.js
git commit -m "feat(ui): signup form + forgot/reset password on landing"
```

---

## Self-Review

**Spec coverage :** store SQLite (T1-2) ✅ · email abstraction (T3) ✅ · auth sur store + require_admin rôle (T4) ✅ · routes register/forgot/reset/verify (T5) ✅ · migration + remap prefs/spots (T6) ✅ · frontend signup+forgot (T7) ✅ · vérif email non bloquante (T5 : compte utilisable, `verify-email` optionnel) ✅ · identité=email (T1 verify renvoie email comme username) ✅ · suppression compte/RGPD → hors périmètre (4.4), non planifié ✅.

**Placeholder scan :** aucun « TBD/TODO ». Le seul point « à adapter aux helpers existants » (T7) référence des fonctions réelles (`API.post`, handler `access-form`) que l'implémenteur voit dans `web/app.js`.

**Type consistency :** `verify_password`/`verify` renvoient `{username,name,role}` (T1, T4) — cohérent avec la session `user` et `require_admin` (T4). `create_token(user_id,kind,ttl_s)`/`consume_token(token,kind)->int|None` cohérents T2↔T5. `_db_path` monkeypatché de façon identique dans tous les tests.

## Notes exécution

- `data/sporia.db` est gitignoré (couvert par `data/` non versionné ; sinon ajouter `data/sporia.db` à `.gitignore`).
- **Non déployé seul** : après merge sur `main`, NE PAS pousser/déployer avant 4.2+4.3 (sinon l'app devient librement inscriptible sans paywall).
- Email en DEV = no-op + log (pas de Brevo requis pour développer/tester).
