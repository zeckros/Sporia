"""Accès bêta : statut 'beta' débloquant, endpoints admin, exposition dans /api/me."""

from __future__ import annotations


def test_has_access_true_for_beta():
    from sporia import billing

    assert billing.has_access({"role": "user", "subscription_status": "beta"}) is True


def test_has_access_still_true_for_active():
    from sporia import billing

    assert billing.has_access({"role": "user", "subscription_status": "active"}) is True


def test_has_access_false_for_none():
    from sporia import billing

    assert billing.has_access({"role": "user", "subscription_status": "none"}) is False
