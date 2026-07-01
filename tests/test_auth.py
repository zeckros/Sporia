"""Characterization of the current auth surface (server.py). Must stay green across the refactor."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

import server


@pytest.fixture
def client():
    return TestClient(server.app)


def test_verify_unknown_user_returns_none():
    assert server._verify("no-such-user", "whatever") is None


def test_verify_wrong_password_returns_none():
    assert server._verify("dev", "wrong-password") is None


def test_protected_route_requires_auth(client):
    r = client.get("/api/dates")
    assert r.status_code == 401


def test_login_bad_credentials_401(client):
    r = client.post("/api/login", json={"username": "dev", "password": "nope"})
    assert r.status_code == 401


def test_me_unauthenticated(client):
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json() == {"authenticated": False, "name": None}


def test_logout_always_ok(client):
    r = client.post("/api/logout")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
