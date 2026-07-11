"""Chantier 3 : écran d'auth unifié (connexion / inscription / lien bêta) en DA."""

from __future__ import annotations

from starlette.testclient import TestClient

from sporia.web.app import app

client = TestClient(app)


def test_auth_screen_has_toggle_and_both_forms():
    html = client.get("/").text
    for marker in (
        'id="login-screen"',
        'id="login-form"',
        'id="login-user"',
        'id="register-form"',
        'id="reg-email"',
        'data-auth-mode="login"',
        'data-auth-mode="register"',
        "goto-beta",
    ):
        assert marker in html, f"marqueur auth manquant: {marker}"
    assert "font-display" in html
