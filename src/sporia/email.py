"""Envoi d'email transactionnel (Brevo). No-op + log si BREVO_API_KEY absent (DEV)."""

from __future__ import annotations

import os

import requests


def send_email(to: str, subject: str, html: str) -> bool:
    key = os.environ.get("BREVO_API_KEY")
    sender = os.environ.get("MAIL_FROM", "no-reply@sporia.duckdns.org")
    if not key:
        print(f"[email] (pas de BREVO_API_KEY) enverrait à {to} : {subject}  # would send")
        return False
    try:
        r = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": key, "content-type": "application/json"},
            json={
                "sender": {"email": sender, "name": "Sporia"},
                "to": [{"email": to}],
                "subject": subject,
                "htmlContent": html,
            },
            timeout=15,
        )
        return r.status_code < 300
    except Exception as e:  # réseau/Brevo down → on ne casse pas la requête utilisateur
        print(f"[email] échec envoi à {to} : {e}")
        return False
