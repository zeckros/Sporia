"""Garde anti-régression du service front : / rend le HTML de l'app, assets statiques servis."""

from __future__ import annotations

from starlette.testclient import TestClient

from sporia.web.app import app

client = TestClient(app)


def test_index_html_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    # marqueurs structurants présents aujourd'hui (cf. index.html)
    assert 'id="app-screen"' in r.text
    assert 'id="map"' in r.text


def test_static_bundle_served():
    # /static est monté sur web/ → le JS applicatif est accessible
    r = client.get("/static/js/main.js")
    assert r.status_code == 200


def test_index_composes_all_screens():
    r = client.get("/")
    assert r.status_code == 200
    # chaque écran (partial) est bien inclus dans le rendu final
    for marker in (
        'id="landing-screen"',
        'id="login-screen"',
        'id="paywall-screen"',
        'id="app-screen"',
        'id="species-modal"',
    ):
        assert marker in r.text
