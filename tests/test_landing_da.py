"""Chantier 2 : landing en DA — assets self-hostés + hooks préservés."""

from __future__ import annotations

from starlette.testclient import TestClient

from sporia.web.app import app

client = TestClient(app)


def test_landing_shroom_assets_served():
    for p in (
        "/static/img/shrooms/girolle.png",
        "/static/img/shrooms/cepe.png",
        "/static/img/shrooms/pied-bleu.png",
    ):
        assert client.get(p).status_code == 200, p


def test_landing_preserves_hooks_and_applies_da():
    html = client.get("/").text
    # contrat de préservation (hooks consommés par main.js)
    for marker in (
        'id="landing-screen"',
        "open-login",
        "data-price-label",
        'id="register-form"',
        'id="reg-email"',
        'id="reg-pass"',
        'id="access-form"',
        'id="ac-email"',
        'id="ac-message"',
        'id="ac-hp"',
        'id="hero"',
        'id="contact"',
        "data-dot",
    ):
        assert marker in html, f"hook manquant: {marker}"
    # DA appliquée : au moins une classe/police DA sur la landing
    assert ("font-display" in html) or ("bg-sousbois" in html) or ("da-grain" in html)
