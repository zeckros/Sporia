"""Fondation DA : polices self-hostées + tokens/utilitaires disponibles."""

from __future__ import annotations

from pathlib import Path

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


def test_da_tokens_in_tailwind_config():
    cfg = Path("tailwind.config.js").read_text(encoding="utf-8").lower()
    assert "girolle" in cfg and "#f2a93b" in cfg
    assert "sousbois" in cfg and "#191510" in cfg
    assert "clash display" in cfg


def test_da_css_variables_and_utilities():
    css = Path("web/css/app.css").read_text(encoding="utf-8")
    assert "#191510" in css and "#f2a93b" in css  # variables DA
    assert ".da-grain" in css and ".da-shadow" in css
