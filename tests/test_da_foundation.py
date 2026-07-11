"""Fondation DA : polices self-hostées + tokens/utilitaires disponibles."""

from __future__ import annotations

from starlette.testclient import TestClient

from sporia.web.app import app

client = TestClient(app)


def test_da_fonts_served():
    for path in (
        "/static/vendor/clash/ClashDisplay-Bold.woff2",
        "/static/vendor/fraunces/Fraunces-Italic.woff2",
        "/static/vendor/spacemono/SpaceMono-Regular.woff2",
    ):
        assert client.get(path).status_code == 200, path


def test_da_fontfaces_declared():
    css = client.get("/static/css/fonts.css").text
    for family in ("Clash Display", "Fraunces", "Space Mono"):
        assert family in css, family
