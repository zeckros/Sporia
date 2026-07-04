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
