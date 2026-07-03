"""Store de comptes SQLite."""

from __future__ import annotations

import pytest

from sporia.users import accounts


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "_db_path", lambda: tmp_path / "t.db")


def test_create_and_get():
    u = accounts.create_user("A@Ex.com", "secret123", name="Al")
    assert u["email"] == "a@ex.com"  # normalisé lower
    assert accounts.get_by_email("a@ex.com")["name"] == "Al"


def test_duplicate_email_raises():
    accounts.create_user("a@ex.com", "secret123")
    with pytest.raises(ValueError):
        accounts.create_user("a@ex.com", "other123")


def test_verify_password():
    accounts.create_user("a@ex.com", "secret123", name="Al", role="admin")
    assert accounts.verify_password("a@ex.com", "wrong") is None
    assert accounts.verify_password("nobody@ex.com", "secret123") is None
    ok = accounts.verify_password("a@ex.com", "secret123")
    assert ok == {"username": "a@ex.com", "name": "Al", "role": "admin"}
