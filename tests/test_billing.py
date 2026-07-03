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
    acc.create_user("a@b.fr", "password123", name="A")

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
    monkeypatch.setattr(billing.stripe.Customer, "create", lambda **k: {"id": "cus_new"})
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

    monkeypatch.setattr(billing.stripe.billing_portal.Session, "create", fake_portal_create)

    url = billing.create_portal_session(acc.get_by_email("a@b.fr"))

    assert url == "https://portal.stripe.test/p/1"
    assert captured["customer"] == "cus_old"
    assert captured["return_url"] == "https://example.test/"


def test_create_portal_session_without_customer_raises(env):
    billing, acc = env
    acc.create_user("a@b.fr", "password123")  # pas de customer
    with pytest.raises(ValueError):
        billing.create_portal_session(acc.get_by_email("a@b.fr"))
