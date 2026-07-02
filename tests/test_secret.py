"""resolve_session_secret : env-only, fail-closed en PROD, éphémère en DEV."""

from __future__ import annotations

import pytest

from sporia.config import resolve_session_secret


def test_strong_secret_from_env_returned(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "z" * 40)
    assert resolve_session_secret(prod=True) == "z" * 40


def test_prod_without_secret_raises(monkeypatch):
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        resolve_session_secret(prod=True)


def test_prod_with_weak_secret_raises(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "change-me")
    with pytest.raises(RuntimeError):
        resolve_session_secret(prod=True)


def test_dev_without_secret_is_ephemeral(monkeypatch):
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    s = resolve_session_secret(prod=False)
    assert isinstance(s, str) and len(s) >= 32
