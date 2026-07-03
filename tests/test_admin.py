"""/api/access-requests is admin-gated (it exposes requesters' emails)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from sporia.web import app as server
from sporia.web.auth import require_admin


def test_access_requests_unauthenticated_401():
    assert TestClient(server.app).get("/api/access-requests").status_code == 401


def test_require_admin_checks_session_role():
    class Req:
        session = {"user": {"username": "u@ex.com", "name": "U", "role": "user"}}

    with pytest.raises(HTTPException):
        require_admin(Req())
