"""Characterization of input-validation contracts on the current API (server.py).

Auth runs before route bodies, so protected routes can only be observed as 401 here;
the validators (_valid_date / _valid_var) are exercised directly."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

import server


@pytest.fixture
def client():
    return TestClient(server.app)


def test_unknown_route_404(client):
    assert client.get("/api/does-not-exist").status_code == 404


@pytest.mark.parametrize("bad", ["", "2026-09-01", "2026099", "abcdefgh", "202609011"])
def test_valid_date_rejects_bad_input(bad):
    with pytest.raises(HTTPException) as exc:
        server._valid_date(bad)
    assert exc.value.status_code == 400


def test_valid_date_accepts_good_input():
    assert server._valid_date("20260901") == "20260901"


@pytest.mark.parametrize("v,expected", [("rr", "RR"), ("T", "T"), ("t", "T")])
def test_valid_var_normalizes(v, expected):
    assert server._valid_var(v) == expected


def test_valid_var_rejects_bad():
    with pytest.raises(HTTPException) as exc:
        server._valid_var("humidity")
    assert exc.value.status_code == 400
