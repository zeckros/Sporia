"""Inscription / reset via TestClient (email mocké)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from sporia.users import accounts
from sporia.web.app import app


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "_db_path", lambda: tmp_path / "t.db")
    import sporia.web.app as appmod

    monkeypatch.setattr(appmod, "send_email", lambda *a, **k: True)


def test_register_then_authenticated():
    c = TestClient(app)
    r = c.post("/api/register", json={"email": "n@ex.com", "password": "secret123", "name": "N"})
    assert r.status_code == 200
    assert c.get("/api/me").json()["authenticated"] is True


def test_register_duplicate_409():
    c = TestClient(app)
    c.post("/api/register", json={"email": "n@ex.com", "password": "secret123"})
    c2 = TestClient(app)
    r = c2.post("/api/register", json={"email": "n@ex.com", "password": "other123"})
    assert r.status_code == 409


def test_forgot_is_neutral_200_even_unknown():
    c = TestClient(app)
    assert c.post("/api/password/forgot", json={"email": "ghost@ex.com"}).status_code == 200


def test_reset_changes_password():
    accounts.create_user("r@ex.com", "old12345")
    uid = accounts.get_by_email("r@ex.com")["id"]
    tok = accounts.create_token(uid, "reset", 600)
    c = TestClient(app)
    assert (
        c.post("/api/password/reset", json={"token": tok, "password": "new12345"}).status_code
        == 200
    )
    assert accounts.verify_password("r@ex.com", "new12345") is not None
