"""Annulation Stripe best-effort (chantier 4.4)."""

import importlib

import pytest


@pytest.fixture()
def billing(monkeypatch, tmp_path):
    monkeypatch.setenv("SPORIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_x")
    import sporia.billing as b

    importlib.reload(b)
    return b


def test_cancel_no_customer_noop(billing):
    billing.cancel_subscription({"stripe_customer_id": None})  # ne lève pas


def test_cancel_deletes_each_subscription(billing, monkeypatch):
    deleted = []
    monkeypatch.setattr(
        billing.stripe.Subscription,
        "list",
        lambda customer: {"data": [{"id": "sub_1"}, {"id": "sub_2"}]},
    )
    monkeypatch.setattr(billing.stripe.Subscription, "delete", lambda sid: deleted.append(sid))
    billing.cancel_subscription({"stripe_customer_id": "cus_1"})
    assert deleted == ["sub_1", "sub_2"]


def test_cancel_swallows_errors(billing, monkeypatch):
    def boom(customer):
        raise RuntimeError("stripe down")

    monkeypatch.setattr(billing.stripe.Subscription, "list", boom)
    billing.cancel_subscription({"stripe_customer_id": "cus_1"})  # ne lève pas
