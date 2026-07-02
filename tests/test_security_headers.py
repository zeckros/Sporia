"""En-têtes de sécurité posés sur les réponses par le middleware security_headers."""

from __future__ import annotations

from starlette.testclient import TestClient

from sporia.web.app import app


def test_core_security_headers_present():
    r = TestClient(app).get("/api/me")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert "Content-Security-Policy" in r.headers
    assert r.headers.get("Permissions-Policy") == "geolocation=(), camera=(), microphone=()"
