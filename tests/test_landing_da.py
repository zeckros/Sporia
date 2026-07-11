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
