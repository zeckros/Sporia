"""Abstraction d'envoi d'email (no-op sans clé)."""

from __future__ import annotations

from sporia.email import send_email


def test_noop_without_key(monkeypatch, capsys):
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    assert send_email("a@ex.com", "Hi", "<p>x</p>") is False
    assert "would send" in capsys.readouterr().out


def test_sends_with_key(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "k")
    calls = {}

    class R:
        status_code = 201

    def fake_post(url, **kw):
        calls["url"] = url
        calls["json"] = kw.get("json")
        return R()

    import sporia.email as em

    monkeypatch.setattr(em.requests, "post", fake_post)
    assert send_email("a@ex.com", "Hi", "<p>x</p>") is True
    assert "brevo.com" in calls["url"]
    assert calls["json"]["to"] == [{"email": "a@ex.com"}]
