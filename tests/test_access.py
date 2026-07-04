"""Règle d'accès abonnement (chantier 4.3)."""

import time

from sporia import billing


def test_none_account_no_access():
    assert billing.has_access(None) is False


def test_admin_always_access():
    assert billing.has_access({"role": "admin", "subscription_status": "none"}) is True


def test_active_status_access():
    assert billing.has_access({"role": "user", "subscription_status": "active"}) is True


def test_grace_period_future_access():
    future = int(time.time()) + 86400
    acc = {"role": "user", "subscription_status": "canceled", "current_period_end": future}
    assert billing.has_access(acc) is True


def test_period_expired_no_access():
    past = int(time.time()) - 86400
    acc = {"role": "user", "subscription_status": "canceled", "current_period_end": past}
    assert billing.has_access(acc) is False


def test_none_status_no_period_no_access():
    acc = {"role": "user", "subscription_status": "none", "current_period_end": None}
    assert billing.has_access(acc) is False
