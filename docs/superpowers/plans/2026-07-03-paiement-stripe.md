# Paiement Stripe (chantier 4.2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vendre l'abonnement annuel Sporia via Stripe et synchroniser automatiquement le statut d'abonné sur le compte (mécanique de paiement uniquement — pas de gating ni d'UI de prix).

**Architecture:** Un module isolé `src/sporia/billing.py` encapsule tout le SDK `stripe` (Checkout hébergé en mode `subscription`, Billing Portal, traitement des webhooks signés). Le store SQLite existant (`src/sporia/users/accounts.py`) gagne 3 helpers pour écrire le statut/customer. Trois routes FastAPI (`/api/billing/checkout`, `/api/billing/portal`, `/api/stripe/webhook`) exposent la mécanique. Config Stripe lue via `os.environ` (comme `email.py`), jamais commitée.

**Tech Stack:** Python 3.10 (prod/CI) / 3.13 (dev), FastAPI + Starlette (`SessionMiddleware`), SDK `stripe`, SQLite (`sqlite3` stdlib), pytest + `TestClient`, `unittest.mock`/monkeypatch pour mocker Stripe.

## Global Constraints

- **Branche dédiée** `chantier-stripe` (base `main`). **NON déployé seul** : merge sur `main`, déploiement seulement avec 4.1 + 4.3.
- **Commits fréquents** (une étape verte = un commit). **PAS de ligne `Co-Authored-By`** dans les messages de commit.
- **Frontend HORS périmètre** (boutons/prix = chantier 4.3). Test par API uniquement.
- **Sans essai gratuit** : Checkout → paiement immédiat.
- **Tous les appels réseau Stripe sont MOCKÉS** dans les tests (aucun appel réel en CI).
- **Secrets via `.env` / `os.environ`** : `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`, `PUBLIC_BASE_URL`. Absents → `stripe_enabled()` False, routes billing en 503, app démarre normalement.
- **Statuts d'abonnement** : `none` (défaut) / `active` / `past_due` / `canceled`.
- **Env Windows** : interpréteur = `venv/Scripts/python.exe` ; tout script imprimant du non-ASCII fait `sys.stdout.reconfigure(encoding="utf-8")` en tête (aucun script nouveau ici, mais règle rappelée).
- **Style existant** : session `user = {"username": <email>, "name": ..., "role": ...}` (pas d'`id` en session → recharger le compte via `accounts.get_by_email(user["username"])`). `require_user` → 401. Routes lèvent `HTTPException`. `from __future__ import annotations` en tête de chaque module.

---

## File Structure

- **Créés :**
  - `src/sporia/billing.py` — intégration Stripe (config env, customer, checkout, portal, webhook).
  - `tests/test_accounts_billing.py` — helpers store abonnement.
  - `tests/test_billing.py` — logique `billing.py` (customer/checkout/portal/process_event), Stripe mocké.
  - `tests/test_billing_routes.py` — routes web (`TestClient`), auth + 503 + webhook.
- **Modifiés :**
  - `src/sporia/users/accounts.py` — +3 helpers (`set_stripe_customer`, `get_by_stripe_customer`, `set_subscription`).
  - `src/sporia/web/app.py` — +3 routes billing, import `from sporia import billing`.
  - `pyproject.toml` — dépendance `stripe`.
  - `requirements.lock` — pin `stripe` (+ transitives éventuelles).
  - `ORACLE_DEPLOY.md` — variables Stripe + création Produit/Prix + endpoint webhook.

---

### Task 1: Dépendance `stripe`

**Files:**
- Modify: `pyproject.toml` (bloc `dependencies`)
- Modify: `requirements.lock`

**Interfaces:**
- Consumes: rien.
- Produces: `import stripe` disponible pour tous les modules suivants.

- [ ] **Step 1: Ajouter la dépendance dans `pyproject.toml`**

Dans le bloc `dependencies = [ ... ]`, ajouter après la ligne `"scikit-learn>=1.7,<1.8",` :

```toml
    "stripe>=9,<13",
```

- [ ] **Step 2: Installer dans le venv de dev**

Run: `venv/Scripts/python.exe -m pip install "stripe>=9,<13"`
Expected: `Successfully installed stripe-<version>` (et éventuellement `typing_extensions`, déjà présent en général).

- [ ] **Step 3: Vérifier l'import**

Run: `venv/Scripts/python.exe -c "import stripe; print(stripe.VERSION)"`
Expected: un numéro de version s'affiche, pas d'erreur.

- [ ] **Step 4: Épingler dans `requirements.lock`**

Récupérer la version exacte : `venv/Scripts/python.exe -m pip show stripe` (ligne `Version:`). Ajouter à `requirements.lock`, **en respectant l'ordre alphabétique** (entre les entrées commençant par `s`), la ligne :

```
stripe==<version exacte>
```

Vérifier que `typing_extensions==<...>` est déjà présent dans le lock (c'est une transitive de fastapi/pydantic — normalement oui). S'il manque, l'ajouter aussi (récupérer la version via `pip show typing_extensions`).

- [ ] **Step 5: Vérifier que le lock est cohérent et auditable**

Run: `venv/Scripts/python.exe -m pip_audit -r requirements.lock` (ou `pip-audit -r requirements.lock` si dispo)
Expected: pas de vulnérabilité (`No known vulnerabilities found`). Si `pip-audit` n'est pas installé en local, sauter cette étape — la CI le lancera (job bloquant existant).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml requirements.lock
git commit -m "build(4.2): add stripe dependency"
```

---

### Task 2: Helpers de store abonnement

**Files:**
- Modify: `src/sporia/users/accounts.py` (ajouts en fin de fichier)
- Test: `tests/test_accounts_billing.py`

**Interfaces:**
- Consumes: helpers internes existants `init_db()`, `_connect()`, `create_user(email, password, name=None, role='user') -> dict`, `get_by_email(email) -> dict | None`.
- Produces:
  - `set_stripe_customer(user_id: int, stripe_customer_id: str) -> None`
  - `get_by_stripe_customer(stripe_customer_id: str) -> dict | None` (dict avec `id`, `email`, `name`, `role`, `subscription_status`, `stripe_customer_id`, `current_period_end`)
  - `set_subscription(user_id: int, status: str, current_period_end: int | None = None) -> None` (idempotent ; ne touche `current_period_end` que s'il est fourni)

- [ ] **Step 1: Écrire les tests (échouants)**

Create `tests/test_accounts_billing.py` :

```python
"""Helpers de store liés à l'abonnement Stripe (chantier 4.2)."""

import importlib

import pytest


@pytest.fixture()
def accounts(tmp_path, monkeypatch):
    """Recharge le module accounts sur une base SQLite temporaire isolée."""
    monkeypatch.setenv("SPORIA_DB", str(tmp_path / "test.db"))
    import sporia.users.accounts as acc

    importlib.reload(acc)
    acc.init_db()
    return acc


def test_set_and_get_by_stripe_customer(accounts):
    u = accounts.create_user("a@b.fr", "password123", name="A")
    accounts.set_stripe_customer(u["id"], "cus_123")

    found = accounts.get_by_stripe_customer("cus_123")
    assert found is not None
    assert found["id"] == u["id"]
    assert found["email"] == "a@b.fr"


def test_get_by_stripe_customer_unknown(accounts):
    assert accounts.get_by_stripe_customer("cus_nope") is None


def test_set_subscription_status_only(accounts):
    u = accounts.create_user("c@d.fr", "password123")
    accounts.set_subscription(u["id"], "active")

    assert accounts.get_by_email("c@d.fr")["subscription_status"] == "active"


def test_set_subscription_with_period_end(accounts):
    u = accounts.create_user("e@f.fr", "password123")
    accounts.set_subscription(u["id"], "active", current_period_end=1893456000)

    row = accounts.get_by_email("e@f.fr")
    assert row["subscription_status"] == "active"
    assert row["current_period_end"] == 1893456000


def test_set_subscription_idempotent(accounts):
    u = accounts.create_user("g@h.fr", "password123")
    accounts.set_subscription(u["id"], "active", current_period_end=1893456000)
    accounts.set_subscription(u["id"], "active")  # sans period_end → ne l'écrase pas

    row = accounts.get_by_email("g@h.fr")
    assert row["subscription_status"] == "active"
    assert row["current_period_end"] == 1893456000  # préservé
```

- [ ] **Step 2: Lancer les tests → échec attendu**

Run: `venv/Scripts/python.exe -m pytest tests/test_accounts_billing.py -v`
Expected: FAIL — `AttributeError: module 'sporia.users.accounts' has no attribute 'set_stripe_customer'`.

- [ ] **Step 3: Implémenter les helpers**

Ajouter à la fin de `src/sporia/users/accounts.py` :

```python


def set_stripe_customer(user_id: int, stripe_customer_id: str) -> None:
    with _connect() as c:
        c.execute(
            "UPDATE users SET stripe_customer_id=?, updated_at=? WHERE id=?",
            (stripe_customer_id, int(time.time()), user_id),
        )


def get_by_stripe_customer(stripe_customer_id: str) -> dict | None:
    init_db()
    with _connect() as c:
        r = c.execute(
            "SELECT * FROM users WHERE stripe_customer_id=?", (stripe_customer_id,)
        ).fetchone()
    return dict(r) if r else None


def set_subscription(user_id: int, status: str, current_period_end: int | None = None) -> None:
    now = int(time.time())
    with _connect() as c:
        if current_period_end is None:
            c.execute(
                "UPDATE users SET subscription_status=?, updated_at=? WHERE id=?",
                (status, now, user_id),
            )
        else:
            c.execute(
                "UPDATE users SET subscription_status=?, current_period_end=?, updated_at=?"
                " WHERE id=?",
                (status, current_period_end, now, user_id),
            )
```

- [ ] **Step 4: Lancer les tests → succès attendu**

Run: `venv/Scripts/python.exe -m pytest tests/test_accounts_billing.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/sporia/users/accounts.py tests/test_accounts_billing.py
git commit -m "feat(4.2): store helpers abonnement (stripe_customer, set_subscription)"
```

---

### Task 3: Module `billing.py` — customer, checkout, portal

**Files:**
- Create: `src/sporia/billing.py`
- Test: `tests/test_billing.py`

**Interfaces:**
- Consumes: `accounts.set_stripe_customer(user_id, cid)`, `accounts.get_by_stripe_customer(cid)`, `accounts.set_subscription(user_id, status, current_period_end=None)` (Task 2) ; SDK `stripe` (Task 1) ; `os.environ`.
- Produces (utilisés par la Task 5) :
  - `stripe_enabled() -> bool`
  - `create_checkout_session(account: dict) -> str` (URL)
  - `create_portal_session(account: dict) -> str` (URL ; lève `ValueError` si le compte n'a pas de `stripe_customer_id`)
  - `WebhookError` (classe d'exception ; définie ici, utilisée par `process_event` en Task 4)
  - `account` est un dict façon `accounts.get_by_email(...)` : contient au moins `id`, `email`, `name`, `stripe_customer_id`.

- [ ] **Step 1: Écrire les tests (échouants)**

Create `tests/test_billing.py` :

```python
"""Logique billing.py (chantier 4.2) — SDK stripe entièrement mocké."""

import importlib

import pytest


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("SPORIA_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_x")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test")
    import sporia.users.accounts as acc

    importlib.reload(acc)
    acc.init_db()
    import sporia.billing as billing

    importlib.reload(billing)
    return billing, acc


def test_stripe_enabled_true_when_env_present(env):
    billing, _ = env
    assert billing.stripe_enabled() is True


def test_stripe_enabled_false_without_key(env, monkeypatch):
    billing, _ = env
    monkeypatch.delenv("STRIPE_SECRET_KEY")
    assert billing.stripe_enabled() is False


def test_ensure_customer_creates_and_persists(env, monkeypatch):
    billing, acc = env
    u = acc.create_user("a@b.fr", "password123", name="A")

    calls = {}

    def fake_create(**kwargs):
        calls.update(kwargs)
        return {"id": "cus_new"}

    monkeypatch.setattr(billing.stripe.Customer, "create", fake_create)

    cid = billing._ensure_customer(acc.get_by_email("a@b.fr"))

    assert cid == "cus_new"
    assert calls["email"] == "a@b.fr"
    assert acc.get_by_email("a@b.fr")["stripe_customer_id"] == "cus_new"


def test_ensure_customer_reuses_existing(env, monkeypatch):
    billing, acc = env
    u = acc.create_user("a@b.fr", "password123")
    acc.set_stripe_customer(u["id"], "cus_old")

    def boom(**kwargs):  # ne doit pas être appelé
        raise AssertionError("stripe.Customer.create ne devrait pas être appelé")

    monkeypatch.setattr(billing.stripe.Customer, "create", boom)

    assert billing._ensure_customer(acc.get_by_email("a@b.fr")) == "cus_old"


def test_create_checkout_session_returns_url(env, monkeypatch):
    billing, acc = env
    acc.create_user("a@b.fr", "password123")
    monkeypatch.setattr(
        billing.stripe.Customer, "create", lambda **k: {"id": "cus_new"}
    )
    captured = {}

    def fake_session_create(**kwargs):
        captured.update(kwargs)
        return {"url": "https://checkout.stripe.test/s/1"}

    monkeypatch.setattr(billing.stripe.checkout.Session, "create", fake_session_create)

    url = billing.create_checkout_session(acc.get_by_email("a@b.fr"))

    assert url == "https://checkout.stripe.test/s/1"
    assert captured["mode"] == "subscription"
    assert captured["customer"] == "cus_new"
    assert captured["line_items"] == [{"price": "price_x", "quantity": 1}]
    assert captured["success_url"] == "https://example.test/?checkout=success"
    assert captured["cancel_url"] == "https://example.test/?checkout=cancel"


def test_create_portal_session_returns_url(env, monkeypatch):
    billing, acc = env
    u = acc.create_user("a@b.fr", "password123")
    acc.set_stripe_customer(u["id"], "cus_old")

    captured = {}

    def fake_portal_create(**kwargs):
        captured.update(kwargs)
        return {"url": "https://portal.stripe.test/p/1"}

    monkeypatch.setattr(
        billing.stripe.billing_portal.Session, "create", fake_portal_create
    )

    url = billing.create_portal_session(acc.get_by_email("a@b.fr"))

    assert url == "https://portal.stripe.test/p/1"
    assert captured["customer"] == "cus_old"
    assert captured["return_url"] == "https://example.test/"


def test_create_portal_session_without_customer_raises(env):
    billing, acc = env
    acc.create_user("a@b.fr", "password123")  # pas de customer
    with pytest.raises(ValueError):
        billing.create_portal_session(acc.get_by_email("a@b.fr"))
```

- [ ] **Step 2: Lancer les tests → échec attendu**

Run: `venv/Scripts/python.exe -m pytest tests/test_billing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sporia.billing'`.

- [ ] **Step 3: Créer `src/sporia/billing.py`**

```python
"""Intégration Stripe : Checkout + Billing Portal + webhooks (chantier 4.2).

Tout l'accès au SDK `stripe` est encapsulé ici. Config lue via l'environnement
(comme email.py) : STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_ID,
PUBLIC_BASE_URL. Clés absentes (DEV) → stripe_enabled() False, l'app démarre
mais les routes billing renvoient 503."""

from __future__ import annotations

import os

import stripe

from sporia.users import accounts

# Stripe subscription.status → notre subscription_status
_STATUS_MAP = {
    "active": "active",
    "trialing": "active",
    "past_due": "past_due",
    "unpaid": "past_due",
    "canceled": "canceled",
    "incomplete_expired": "canceled",
}


class WebhookError(Exception):
    """Signature invalide ou payload webhook illisible."""


def stripe_enabled() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY") and os.environ.get("STRIPE_PRICE_ID"))


def _base_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")


def _configure() -> None:
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")


def _ensure_customer(account: dict) -> str:
    """Renvoie le stripe_customer_id du compte, en le créant si besoin."""
    cid = account.get("stripe_customer_id")
    if cid:
        return cid
    _configure()
    customer = stripe.Customer.create(
        email=account["email"],
        name=account.get("name") or account["email"],
        metadata={"user_id": str(account["id"])},
    )
    accounts.set_stripe_customer(account["id"], customer["id"])
    return customer["id"]


def create_checkout_session(account: dict) -> str:
    """Crée une Checkout Session (abonnement) et renvoie son URL hébergée."""
    _configure()
    cid = _ensure_customer(account)
    base = _base_url()
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=cid,
        line_items=[{"price": os.environ["STRIPE_PRICE_ID"], "quantity": 1}],
        success_url=f"{base}/?checkout=success",
        cancel_url=f"{base}/?checkout=cancel",
        client_reference_id=str(account["id"]),
    )
    return session["url"]


def create_portal_session(account: dict) -> str:
    """Crée une session Billing Portal et renvoie son URL. Lève ValueError sans customer."""
    cid = account.get("stripe_customer_id")
    if not cid:
        raise ValueError("compte sans stripe_customer_id")
    _configure()
    session = stripe.billing_portal.Session.create(customer=cid, return_url=f"{_base_url()}/")
    return session["url"]
```

- [ ] **Step 4: Lancer les tests → succès attendu**

Run: `venv/Scripts/python.exe -m pytest tests/test_billing.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Vérifier lint**

Run: `venv/Scripts/python.exe -m ruff check src/sporia/billing.py tests/test_billing.py`
Expected: `All checks passed!` (le `u` non utilisé dans certains tests peut déclencher F841 — si c'est le cas, retirer l'affectation `u = ` là où `u` n'est pas relu).

- [ ] **Step 6: Commit**

```bash
git add src/sporia/billing.py tests/test_billing.py
git commit -m "feat(4.2): billing.py — checkout + portal Stripe (customer lazy)"
```

---

### Task 4: `billing.py` — traitement des webhooks (`process_event`)

**Files:**
- Modify: `src/sporia/billing.py` (ajout de `process_event` + `_update`)
- Test: `tests/test_billing.py` (ajout de cas)

**Interfaces:**
- Consumes: `stripe.Webhook.construct_event(payload, sig_header, secret)`, `accounts.get_by_stripe_customer(cid)`, `accounts.set_subscription(user_id, status, current_period_end=None)`, `WebhookError`, `_STATUS_MAP`.
- Produces (utilisé par la Task 5) : `process_event(payload: bytes, sig_header: str) -> None` — lève `WebhookError` si la signature/le payload est invalide ; sinon met à jour le compte de façon idempotente (customer inconnu → no-op).

- [ ] **Step 1: Ajouter les tests (échouants)**

Ajouter à la fin de `tests/test_billing.py` :

```python


def _event(etype, obj):
    return {"type": etype, "data": {"object": obj}}


def test_process_event_checkout_completed_activates(env, monkeypatch):
    billing, acc = env
    u = acc.create_user("a@b.fr", "password123")
    acc.set_stripe_customer(u["id"], "cus_1")
    monkeypatch.setattr(
        billing.stripe.Webhook,
        "construct_event",
        lambda payload, sig, secret: _event(
            "checkout.session.completed", {"customer": "cus_1", "subscription": "sub_1"}
        ),
    )

    billing.process_event(b"{}", "sig")

    assert acc.get_by_email("a@b.fr")["subscription_status"] == "active"


def test_process_event_subscription_updated_past_due(env, monkeypatch):
    billing, acc = env
    u = acc.create_user("a@b.fr", "password123")
    acc.set_stripe_customer(u["id"], "cus_1")
    monkeypatch.setattr(
        billing.stripe.Webhook,
        "construct_event",
        lambda payload, sig, secret: _event(
            "customer.subscription.updated",
            {"customer": "cus_1", "status": "past_due", "current_period_end": 1893456000},
        ),
    )

    billing.process_event(b"{}", "sig")

    row = acc.get_by_email("a@b.fr")
    assert row["subscription_status"] == "past_due"
    assert row["current_period_end"] == 1893456000


def test_process_event_subscription_deleted_cancels(env, monkeypatch):
    billing, acc = env
    u = acc.create_user("a@b.fr", "password123")
    acc.set_stripe_customer(u["id"], "cus_1")
    monkeypatch.setattr(
        billing.stripe.Webhook,
        "construct_event",
        lambda payload, sig, secret: _event(
            "customer.subscription.deleted",
            {"customer": "cus_1", "current_period_end": 1893456000},
        ),
    )

    billing.process_event(b"{}", "sig")

    assert acc.get_by_email("a@b.fr")["subscription_status"] == "canceled"


def test_process_event_invoice_payment_failed(env, monkeypatch):
    billing, acc = env
    u = acc.create_user("a@b.fr", "password123")
    acc.set_stripe_customer(u["id"], "cus_1")
    monkeypatch.setattr(
        billing.stripe.Webhook,
        "construct_event",
        lambda payload, sig, secret: _event(
            "invoice.payment_failed", {"customer": "cus_1"}
        ),
    )

    billing.process_event(b"{}", "sig")

    assert acc.get_by_email("a@b.fr")["subscription_status"] == "past_due"


def test_process_event_unknown_customer_noop(env, monkeypatch):
    billing, acc = env
    monkeypatch.setattr(
        billing.stripe.Webhook,
        "construct_event",
        lambda payload, sig, secret: _event(
            "checkout.session.completed", {"customer": "cus_ghost"}
        ),
    )
    # ne doit pas lever
    billing.process_event(b"{}", "sig")


def test_process_event_ignored_type_noop(env, monkeypatch):
    billing, acc = env
    u = acc.create_user("a@b.fr", "password123")
    acc.set_stripe_customer(u["id"], "cus_1")
    monkeypatch.setattr(
        billing.stripe.Webhook,
        "construct_event",
        lambda payload, sig, secret: _event("customer.created", {"customer": "cus_1"}),
    )

    billing.process_event(b"{}", "sig")

    assert acc.get_by_email("a@b.fr")["subscription_status"] == "none"  # inchangé


def test_process_event_bad_signature_raises(env, monkeypatch):
    billing, _ = env

    def boom(payload, sig, secret):
        raise ValueError("bad signature")

    monkeypatch.setattr(billing.stripe.Webhook, "construct_event", boom)

    with pytest.raises(billing.WebhookError):
        billing.process_event(b"{}", "bad")
```

- [ ] **Step 2: Lancer les tests → échec attendu**

Run: `venv/Scripts/python.exe -m pytest tests/test_billing.py -k process_event -v`
Expected: FAIL — `AttributeError: module 'sporia.billing' has no attribute 'process_event'`.

- [ ] **Step 3: Implémenter `process_event` + `_update`**

Ajouter à la fin de `src/sporia/billing.py` :

```python


def process_event(payload: bytes, sig_header: str) -> None:
    """Vérifie la signature Stripe puis applique l'événement (idempotent).

    Lève WebhookError si la signature ou le payload est invalide."""
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except (stripe.error.SignatureVerificationError, ValueError) as e:
        raise WebhookError(str(e)) from e

    etype = event["type"]
    obj = event["data"]["object"]
    customer_id = obj.get("customer")

    if etype == "checkout.session.completed":
        _update(customer_id, "active", None)
    elif etype == "customer.subscription.updated":
        _update(customer_id, _STATUS_MAP.get(obj.get("status"), "active"), obj.get("current_period_end"))
    elif etype == "customer.subscription.deleted":
        _update(customer_id, "canceled", obj.get("current_period_end"))
    elif etype == "invoice.payment_failed":
        _update(customer_id, "past_due", None)
    # autres types → ignorés (no-op)


def _update(customer_id: str | None, status: str, period_end: int | None) -> None:
    if not customer_id:
        return
    acc = accounts.get_by_stripe_customer(customer_id)
    if acc is None:
        print(f"[billing] webhook pour customer inconnu {customer_id} — ignoré")
        return
    accounts.set_subscription(acc["id"], status, period_end)
```

- [ ] **Step 4: Lancer tous les tests billing → succès attendu**

Run: `venv/Scripts/python.exe -m pytest tests/test_billing.py -v`
Expected: PASS (14 tests au total).

- [ ] **Step 5: Vérifier lint (ligne longue possible)**

Run: `venv/Scripts/python.exe -m ruff check src/sporia/billing.py`
Expected: `All checks passed!`. Si E501 sur la ligne `customer.subscription.updated`, la scinder :

```python
    elif etype == "customer.subscription.updated":
        status = _STATUS_MAP.get(obj.get("status"), "active")
        _update(customer_id, status, obj.get("current_period_end"))
```

- [ ] **Step 6: Commit**

```bash
git add src/sporia/billing.py tests/test_billing.py
git commit -m "feat(4.2): webhook process_event (signé, idempotent) -> statut compte"
```

---

### Task 5: Routes web (`checkout`, `portal`, `webhook`)

**Files:**
- Modify: `src/sporia/web/app.py` (import + 3 routes)
- Test: `tests/test_billing_routes.py`

**Interfaces:**
- Consumes: `billing.stripe_enabled()`, `billing.create_checkout_session(account)`, `billing.create_portal_session(account)`, `billing.process_event(payload, sig)`, `billing.WebhookError` (Tasks 3-4) ; `accounts.get_by_email(email)`, `accounts.create_user(...)` ; `require_user` (existant) ; `billing.stripe.Webhook.construct_event` pour les tests.
- Produces: routes `POST /api/billing/checkout`, `POST /api/billing/portal`, `POST /api/stripe/webhook`.

- [ ] **Step 1: Écrire les tests (échouants)**

Create `tests/test_billing_routes.py` :

```python
"""Routes billing (chantier 4.2) via TestClient — Stripe mocké."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SPORIA_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)  # DEV : secret fort pour SessionMiddleware
    # Stripe désactivé par défaut (pas de clés) — activé au cas par cas dans les tests.
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_PRICE_ID", raising=False)

    import sporia.users.accounts as acc

    importlib.reload(acc)
    acc.init_db()
    import sporia.billing as billing

    importlib.reload(billing)
    import sporia.web.app as webapp

    importlib.reload(webapp)
    return TestClient(webapp.app), acc, billing, webapp


def _login(client, acc, email="u@sporia.fr", password="password123"):
    acc.create_user(email, password, name="U")
    r = client.post("/api/login", json={"username": email, "password": password})
    assert r.status_code == 200


def test_checkout_requires_auth(client):
    c, acc, billing, webapp = client
    assert c.post("/api/billing/checkout").status_code == 401


def test_portal_requires_auth(client):
    c, acc, billing, webapp = client
    assert c.post("/api/billing/portal").status_code == 401


def test_checkout_503_when_disabled(client):
    c, acc, billing, webapp = client
    _login(c, acc)
    assert c.post("/api/billing/checkout").status_code == 503


def test_checkout_returns_url_when_enabled(client, monkeypatch):
    c, acc, billing, webapp = client
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_x")
    _login(c, acc)
    monkeypatch.setattr(
        billing, "create_checkout_session", lambda account: "https://checkout.test/1"
    )

    r = c.post("/api/billing/checkout")

    assert r.status_code == 200
    assert r.json()["url"] == "https://checkout.test/1"


def test_portal_400_without_customer(client, monkeypatch):
    c, acc, billing, webapp = client
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_x")
    _login(c, acc)  # compte sans customer → create_portal_session lève ValueError

    assert c.post("/api/billing/portal").status_code == 400


def test_webhook_bad_signature_400(client, monkeypatch):
    c, acc, billing, webapp = client
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")

    def boom(payload, sig, secret):
        raise ValueError("bad")

    monkeypatch.setattr(billing.stripe.Webhook, "construct_event", boom)

    r = c.post("/api/stripe/webhook", content=b"{}", headers={"stripe-signature": "bad"})
    assert r.status_code == 400


def test_webhook_valid_event_updates_account(client, monkeypatch):
    c, acc, billing, webapp = client
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")
    u = acc.create_user("sub@sporia.fr", "password123")
    acc.set_stripe_customer(u["id"], "cus_1")
    monkeypatch.setattr(
        billing.stripe.Webhook,
        "construct_event",
        lambda payload, sig, secret: {
            "type": "checkout.session.completed",
            "data": {"object": {"customer": "cus_1"}},
        },
    )

    r = c.post("/api/stripe/webhook", content=b"{}", headers={"stripe-signature": "ok"})

    assert r.status_code == 200
    assert acc.get_by_email("sub@sporia.fr")["subscription_status"] == "active"
```

- [ ] **Step 2: Lancer les tests → échec attendu**

Run: `venv/Scripts/python.exe -m pytest tests/test_billing_routes.py -v`
Expected: FAIL — les routes renvoient 404 (non définies).

- [ ] **Step 3: Ajouter l'import billing dans `app.py`**

Dans `src/sporia/web/app.py`, à côté des imports `from sporia import api as core` (ligne ~24), ajouter :

```python
from sporia import billing
```

- [ ] **Step 4: Ajouter les routes après `verify_email` (après la ligne ~212)**

Insérer, juste avant le commentaire `# ===== API données (protégées) =====` :

```python
# ===== Paiement / abonnement (Stripe) =====
@app.post("/api/billing/checkout")
def billing_checkout(user=Depends(require_user)):
    if not billing.stripe_enabled():
        raise HTTPException(status_code=503, detail="Paiement indisponible.")
    account = accounts.get_by_email(user["username"])
    return {"url": billing.create_checkout_session(account)}


@app.post("/api/billing/portal")
def billing_portal(user=Depends(require_user)):
    if not billing.stripe_enabled():
        raise HTTPException(status_code=503, detail="Paiement indisponible.")
    account = accounts.get_by_email(user["username"])
    try:
        url = billing.create_portal_session(account)
    except ValueError:
        raise HTTPException(status_code=400, detail="Aucun abonnement à gérer.") from None
    return {"url": url}


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        billing.process_event(payload, sig)
    except billing.WebhookError:
        raise HTTPException(status_code=400, detail="Webhook invalide.") from None
    return {"received": True}
```

- [ ] **Step 5: Lancer les tests → succès attendu**

Run: `venv/Scripts/python.exe -m pytest tests/test_billing_routes.py -v`
Expected: PASS (8 tests).

- [ ] **Step 6: Suite complète + lint**

Run: `venv/Scripts/python.exe -m pytest -q` puis `venv/Scripts/python.exe -m ruff check src tests`
Expected: tous les tests passent (les 64 de 4.1 + les nouveaux) ; `All checks passed!`.

- [ ] **Step 7: Commit**

```bash
git add src/sporia/web/app.py tests/test_billing_routes.py
git commit -m "feat(4.2): routes /api/billing/checkout, /portal, /stripe/webhook"
```

---

### Task 6: Documentation de déploiement

**Files:**
- Modify: `ORACLE_DEPLOY.md`

**Interfaces:**
- Consumes: rien (documentation).
- Produces: procédure Stripe pour le déploiement conjoint 4.1 + 4.2 + 4.3.

- [ ] **Step 1: Ajouter une section Stripe dans `ORACLE_DEPLOY.md`**

Repérer la section décrivant le `.env` / les variables d'environnement (là où `SESSION_SECRET` et `BREVO_API_KEY` sont documentés) et y ajouter :

```markdown
### Abonnement Stripe (chantier 4.2)

Dans le dashboard Stripe (mode **test** d'abord, **live** au go-live) :

1. **Produit + Prix** : créer un produit « Sporia » avec un **prix récurrent annuel**
   (montant ~10-20 €/an). Copier l'identifiant du prix (`price_...`).
2. **Webhook** : créer un endpoint `https://sporia.duckdns.org/api/stripe/webhook`,
   abonné aux événements `checkout.session.completed`, `customer.subscription.updated`,
   `customer.subscription.deleted`, `invoice.payment_failed`. Copier le secret de
   signature (`whsec_...`).
3. **Clé API** : récupérer la clé secrète (`sk_live_...` / `sk_test_...`).

Ajouter au `.env` du serveur (chargé par systemd `EnvironmentFile`) :

```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_...
PUBLIC_BASE_URL=https://sporia.duckdns.org
```

Sans ces variables, l'app démarre normalement mais les routes de paiement
renvoient **503** (fonctionnalité désactivée). Le passage en clés **live**
nécessite la vérification d'identité du compte Stripe.

> nginx : `/api/stripe/webhook` passe par le proxy `/api/` sans authentification
> (appelé par Stripe). Vérifier que le rate-limiting `/api/` ne bloque pas les
> rafales de webhooks.
```

- [ ] **Step 2: Commit**

```bash
git add ORACLE_DEPLOY.md
git commit -m "docs(4.2): procédure déploiement Stripe (produit/prix/webhook/.env)"
```

---

## Vérification finale

1. `venv/Scripts/python.exe -m pytest -q` → tout vert (4.1 + 4.2).
2. `venv/Scripts/python.exe -m ruff check src tests` → `All checks passed!`.
3. **Manuel (mode test Stripe, optionnel hors CI)** : `.env` avec clés de test + `STRIPE_PRICE_ID` d'un prix test ; `stripe listen --forward-to localhost:8000/api/stripe/webhook` ; connecté → `POST /api/billing/checkout` → ouvrir l'URL → payer `4242 4242 4242 4242` → webhook → compte `active` en base ; annuler via le portail → webhook → `canceled`.
4. `stripe_enabled()` False (pas de clés) → routes billing renvoient 503, le reste de l'app fonctionne (démarrage, login, overlays).

## Hors périmètre (rappel)

Gating/paywall + affichage du prix + boutons UI (4.3) · CGV/mentions/droit de rétractation (4.4) · refonte UX (4.5) · essai gratuit (`trial_period_days`, ajout futur trivial) · plusieurs plans/tarifs.
