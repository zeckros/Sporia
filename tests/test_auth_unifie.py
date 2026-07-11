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


def test_register_form_moved_not_duplicated():
    """L'inscription est retirée de la landing → une seule occurrence dans le rendu."""
    html = client.get("/").text
    assert html.count('id="register-form"') == 1
    assert 'id="access-form"' in html  # la bêta reste (dans la landing)
