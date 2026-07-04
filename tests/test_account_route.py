"""Route de suppression de compte (chantier 4.4)."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SPORIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    import sporia.config as cfg

    monkeypatch.setattr(cfg.settings, "base_dir", tmp_path)  # data_dir = tmp_path/"data"
    import sporia.users.accounts as acc
    import sporia.users.prefs as prefs
    import sporia.users.spots as spots

    importlib.reload(acc)
    importlib.reload(prefs)
    importlib.reload(spots)
    acc.init_db()
    import sporia.billing as billing

    importlib.reload(billing)
    import sporia.web.app as webapp

    importlib.reload(webapp)
    return TestClient(webapp.app), acc, prefs, spots


def test_delete_requires_auth(client):
    c, *_ = client
    assert c.delete("/api/account").status_code == 401


def test_delete_purges_everything(client):
    c, acc, prefs, spots = client
    acc.create_user("a@b.fr", "password123", name="A")
    c.post("/api/login", json={"username": "a@b.fr", "password": "password123"})
    prefs.set_species("a@b.fr", ["Boletus edulis"])
    spots.add_spot("a@b.fr", 46.0, 2.0, "coin")

    r = c.delete("/api/account")
    assert r.status_code == 200

    assert acc.get_by_email("a@b.fr") is None
    assert prefs.get_species("a@b.fr") is None
    assert spots.list_spots("a@b.fr") == []
    assert c.get("/api/me").json()["authenticated"] is False
