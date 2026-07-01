"""Migration des modules utilisateurs vers sporia.users — comportement inchangé."""

from __future__ import annotations


def test_prefs_roundtrip(tmp_path, monkeypatch):
    from sporia.users import prefs

    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "user_prefs.json")
    assert prefs.get_species("nobody") is None
    prefs.set_species("u1", ["Boletus edulis"])
    assert prefs.get_species("u1") == ["Boletus edulis"]


def test_spots_add_and_list(tmp_path, monkeypatch):
    from sporia.users import spots

    monkeypatch.setattr(spots, "_path", lambda: tmp_path / "user_spots.json")
    assert spots.list_spots("u1") == []
    s = spots.add_spot("u1", 46.5, 2.5, "coin")
    assert spots.list_spots("u1")[0]["id"] == s["id"]


def test_access_request_capped_and_listed(tmp_path, monkeypatch):
    from sporia.users import access_requests

    monkeypatch.setattr(access_requests, "_path", lambda: tmp_path / "access_requests.json")
    access_requests.add_request("Alice", "a@b.co", "hello")
    reqs = access_requests.list_requests()
    assert reqs[-1]["name"] == "Alice"
    assert reqs[-1]["email"] == "a@b.co"


def test_root_shims_reexport():
    import user_prefs
    import user_spots

    assert hasattr(user_prefs, "get_species")
    assert hasattr(user_spots, "list_spots")
