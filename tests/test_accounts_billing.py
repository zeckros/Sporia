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
