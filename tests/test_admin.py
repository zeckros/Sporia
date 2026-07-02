"""/api/access-requests is admin-gated (it exposes requesters' emails)."""

from __future__ import annotations

from starlette.testclient import TestClient

from sporia.web import app as server
from sporia.web.auth import admin_usernames


def test_access_requests_unauthenticated_401():
    assert TestClient(server.app).get("/api/access-requests").status_code == 401


def test_admin_usernames_reads_role():
    cfg = {"credentials": {"usernames": {"a": {"role": "admin"}, "b": {"role": None}, "c": {}}}}
    assert admin_usernames(cfg) == {"a"}
