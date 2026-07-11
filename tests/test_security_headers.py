"""En-têtes de sécurité posés sur les réponses par le middleware security_headers."""

from __future__ import annotations

from starlette.testclient import TestClient

from sporia.web.app import app


def test_core_security_headers_present():
    r = TestClient(app).get("/api/me")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert "Content-Security-Policy" in r.headers
    assert r.headers.get("Permissions-Policy") == "geolocation=(self), camera=(), microphone=()"


def test_csp_has_no_external_cdn():
    r = TestClient(app).get("/")
    csp = r.headers["Content-Security-Policy"]
    for host in ("cdn.tailwindcss.com", "unpkg.com", "fonts.googleapis.com", "fonts.gstatic.com"):
        assert host not in csp, f"CSP ne doit plus référencer {host}"
    assert "default-src 'self'" in csp
