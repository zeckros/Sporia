"""Accès bêta : statut 'beta' débloquant, endpoints admin, exposition dans /api/me."""

from __future__ import annotations

import importlib

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
