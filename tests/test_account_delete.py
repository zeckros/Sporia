"""Purge des données d'un compte (chantier 4.4)."""

import importlib

import pytest


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    monkeypatch.setenv("SPORIA_DB", str(tmp_path / "t.db"))
    import sporia.config as cfg

    monkeypatch.setattr(cfg.settings, "base_dir", tmp_path)  # data_dir = tmp_path/"data"
    import sporia.users.accounts as acc
    import sporia.users.prefs as prefs
    import sporia.users.spots as spots

    importlib.reload(acc)
    importlib.reload(prefs)
    importlib.reload(spots)
    acc.init_db()
    return acc, prefs, spots


def test_accounts_delete_user_removes_row_and_tokens(stores):
    acc, _, _ = stores
    u = acc.create_user("a@b.fr", "password123")
    acc.create_token(u["id"], "reset", 3600)
    acc.delete_user(u["id"])
    assert acc.get_by_email("a@b.fr") is None
    assert acc.consume_token("whatever", "reset") is None  # table vidée pour ce user


def test_accounts_delete_user_idempotent(stores):
    acc, _, _ = stores
    u = acc.create_user("a@b.fr", "password123")
    acc.delete_user(u["id"])
    acc.delete_user(u["id"])  # ne lève pas


def test_prefs_delete_user(stores):
    _, prefs, _ = stores
    prefs.set_species("a@b.fr", ["Boletus edulis"])
    prefs.set_species("c@d.fr", ["Cantharellus cibarius"])
    prefs.delete_user("a@b.fr")
    assert prefs.get_species("a@b.fr") is None
    assert prefs.get_species("c@d.fr") == ["Cantharellus cibarius"]
    prefs.delete_user("a@b.fr")  # no-op, ne lève pas


def test_spots_delete_user(stores):
    _, _, spots = stores
    spots.add_spot("a@b.fr", 46.0, 2.0, "coin")
    spots.add_spot("c@d.fr", 47.0, 3.0, "autre")
    spots.delete_user("a@b.fr")
    assert spots.list_spots("a@b.fr") == []
    assert len(spots.list_spots("c@d.fr")) == 1
