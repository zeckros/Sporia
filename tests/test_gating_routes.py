"""Gating abonnement sur les routes data (chantier 4.3) — TestClient."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SPORIA_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.setenv("SPORIA_PRICE_LABEL", "12 €/an")

    import sporia.users.accounts as acc

    importlib.reload(acc)
    acc.init_db()
    import sporia.billing as billing

    importlib.reload(billing)
    import sporia.web.app as webapp

    importlib.reload(webapp)
    return TestClient(webapp.app), acc


def _login(c, acc, email, password="password123", role="user", status="none"):
    u = acc.create_user(email, password, name="U", role=role)
    if status != "none":
        acc.set_subscription(u["id"], status)
    r = c.post("/api/login", json={"username": email, "password": password})
    assert r.status_code == 200
    return u


def test_data_route_402_without_subscription(client):
    c, acc = client
    _login(c, acc, "free@sporia.fr")
    r = c.get("/api/outline")
    assert r.status_code == 402


def test_data_route_not_402_with_subscription(client):
    c, acc = client
    _login(c, acc, "sub@sporia.fr", status="active")
    r = c.get("/api/outline")
    assert r.status_code != 402  # 200 attendu (route sans I/O lourde)


def test_data_route_not_402_for_admin(client):
    c, acc = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    r = c.get("/api/outline")
    assert r.status_code != 402


def test_me_unauthenticated_public(client):
    c, acc = client
    r = c.get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is False
    assert body["subscribed"] is False
    assert body["price_label"] == "12 €/an"


def test_me_authenticated_subscribed_flag(client):
    c, acc = client
    _login(c, acc, "sub@sporia.fr", status="active")
    body = c.get("/api/me").json()
    assert body["authenticated"] is True
    assert body["subscribed"] is True


def test_public_routes_not_gated(client):
    c, acc = client
    # register (public) ne doit jamais renvoyer 402
    r = c.post(
        "/api/register",
        json={"email": "new@sporia.fr", "password": "password123", "name": "N"},
    )
    assert r.status_code != 402
