"""Accès bêta : statut 'beta' débloquant, endpoints admin, exposition dans /api/me."""

from __future__ import annotations

import importlib
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SPORIA_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)

    import sporia.users.accounts as acc

    importlib.reload(acc)
    acc.init_db()
    import sporia.billing as billing

    importlib.reload(billing)
    import sporia.web.app as webapp

    importlib.reload(webapp)
    # `settings.data_dir` n'est pas configurable par l'environnement : sans ce patch,
    # les demandes d'accès des tests s'écriraient dans le data/ du dépôt.
    import sporia.users.access_requests as areq

    monkeypatch.setattr(areq, "_path", lambda: tmp_path / "access_requests.json")
    return TestClient(webapp.app), acc, webapp


def _login(client, acc, email, password="password123", role="user"):
    acc.create_user(email, password, name="U", role=role)
    r = client.post("/api/login", json={"username": email, "password": password})
    assert r.status_code == 200, r.text


def test_account_from_request_is_beta(client):
    c, acc, webapp = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    from sporia.users import access_requests

    req = access_requests.add_request("Testeur", "testeur@sporia.fr", "Je veux tester")
    r = c.post("/api/admin/accounts/from-request", json={"request_id": req["id"]})
    assert r.status_code == 200, r.text
    created = acc.get_by_email("testeur@sporia.fr")
    assert created["subscription_status"] == "beta"


def test_beta_account_passes_the_paywall(client):
    """Le test qui compte vraiment : la barrière 402 s'ouvre pour un bêta."""
    c, acc, webapp = client
    _login(c, acc, "testeur@sporia.fr")
    assert c.get("/api/dates").status_code == 402

    compte = acc.get_by_email("testeur@sporia.fr")
    acc.set_subscription(compte["id"], "beta")
    assert c.get("/api/dates").status_code == 200


def test_has_access_true_for_beta():
    from sporia import billing

    assert billing.has_access({"role": "user", "subscription_status": "beta"}) is True


def test_has_access_still_true_for_active():
    from sporia import billing

    assert billing.has_access({"role": "user", "subscription_status": "active"}) is True


def test_has_access_false_for_none():
    from sporia import billing

    assert billing.has_access({"role": "user", "subscription_status": "none"}) is False


def test_list_accounts_excludes_secrets_and_sorts_recent_first(client):
    c, acc, webapp = client
    acc.create_user("premier@sporia.fr", "password123", name="Premier")
    acc.create_user("second@sporia.fr", "password123", name="Second")
    rows, truncated = acc.list_accounts()
    assert truncated is False
    assert [r["email"] for r in rows][:2] == ["second@sporia.fr", "premier@sporia.fr"]
    assert set(rows[0]) == {
        "id",
        "email",
        "name",
        "role",
        "subscription_status",
        "current_period_end",
        "created_at",
    }


def test_list_accounts_flags_truncation(client):
    c, acc, webapp = client
    for i in range(3):
        acc.create_user(f"u{i}@sporia.fr", "password123")
    rows, truncated = acc.list_accounts(limit=2)
    assert len(rows) == 2
    assert truncated is True


def test_list_accounts_not_truncated_at_exact_limit(client):
    c, acc, webapp = client
    for i in range(3):
        acc.create_user(f"u{i}@sporia.fr", "password123")
    rows, truncated = acc.list_accounts(limit=3)
    assert len(rows) == 3
    assert truncated is False


def test_admin_accounts_requires_admin(client):
    c, acc, webapp = client
    _login(c, acc, "simple@sporia.fr")
    assert c.get("/api/admin/accounts").status_code == 403


def test_admin_accounts_lists_without_secrets(client):
    c, acc, webapp = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    r = c.get("/api/admin/accounts")
    assert r.status_code == 200
    body = r.json()
    assert body["truncated"] is False
    assert "password_hash" not in body["accounts"][0]
    assert "stripe_customer_id" not in body["accounts"][0]


def test_set_access_toggles_beta_then_back(client):
    c, acc, webapp = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    acc.create_user("testeur@sporia.fr", "password123")

    r = c.post("/api/admin/accounts/access", json={"email": "testeur@sporia.fr", "status": "beta"})
    assert r.status_code == 200, r.text
    assert acc.get_by_email("testeur@sporia.fr")["subscription_status"] == "beta"

    r = c.post("/api/admin/accounts/access", json={"email": "testeur@sporia.fr", "status": "none"})
    assert r.status_code == 200
    assert acc.get_by_email("testeur@sporia.fr")["subscription_status"] == "none"


def test_set_access_unknown_email_404(client):
    c, acc, webapp = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    r = c.post("/api/admin/accounts/access", json={"email": "inconnu@sporia.fr", "status": "beta"})
    assert r.status_code == 404


def test_set_access_refuses_admin_account_409(client):
    c, acc, webapp = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    acc.create_user("autre-admin@sporia.fr", "password123", role="admin")
    r = c.post(
        "/api/admin/accounts/access", json={"email": "autre-admin@sporia.fr", "status": "beta"}
    )
    assert r.status_code == 409


def test_set_access_refuses_paying_account_409(client):
    c, acc, webapp = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    payant = acc.create_user("payant@sporia.fr", "password123")
    acc.set_subscription(payant["id"], "active")
    r = c.post("/api/admin/accounts/access", json={"email": "payant@sporia.fr", "status": "beta"})
    assert r.status_code == 409


def test_set_access_refuses_grace_period_account_409(client):
    """Statut 'canceled' mais current_period_end futur = grâce Stripe, pas à écraser."""
    c, acc, webapp = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    compte = acc.create_user("grace@sporia.fr", "password123")
    acc.set_subscription(compte["id"], "canceled", int(time.time()) + 3600)
    r = c.post("/api/admin/accounts/access", json={"email": "grace@sporia.fr", "status": "beta"})
    assert r.status_code == 409


def test_set_access_allows_expired_grace_period_account(client):
    """Même statut 'canceled', mais current_period_end passé : la bascule doit réussir."""
    c, acc, webapp = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    compte = acc.create_user("expire@sporia.fr", "password123")
    acc.set_subscription(compte["id"], "canceled", int(time.time()) - 3600)
    r = c.post("/api/admin/accounts/access", json={"email": "expire@sporia.fr", "status": "beta"})
    assert r.status_code == 200, r.text
    assert acc.get_by_email("expire@sporia.fr")["subscription_status"] == "beta"


def test_set_access_rejects_invalid_status_400(client):
    c, acc, webapp = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    acc.create_user("testeur@sporia.fr", "password123")
    r = c.post("/api/admin/accounts/access", json={"email": "testeur@sporia.fr", "status": "admin"})
    assert r.status_code == 400


def test_me_access_none_then_beta(client):
    c, acc, webapp = client
    _login(c, acc, "testeur@sporia.fr")
    assert c.get("/api/me").json()["access"] == "none"

    compte = acc.get_by_email("testeur@sporia.fr")
    acc.set_subscription(compte["id"], "beta")
    body = c.get("/api/me").json()
    assert body["access"] == "beta"
    assert body["subscribed"] is True


def test_me_access_admin(client):
    c, acc, webapp = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    assert c.get("/api/me").json()["access"] == "admin"


def test_me_access_paid(client):
    c, acc, webapp = client
    _login(c, acc, "payant@sporia.fr")
    compte = acc.get_by_email("payant@sporia.fr")
    acc.set_subscription(compte["id"], "active")
    assert c.get("/api/me").json()["access"] == "paid"


def test_me_access_none_when_anonymous(client):
    c, acc, webapp = client
    assert c.get("/api/me").json()["access"] == "none"
