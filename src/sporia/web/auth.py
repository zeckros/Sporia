"""Authentification par comptes (store SQLite) + dépendances FastAPI.

`verify` renvoie None si l'email est inconnu ou le mot de passe faux (temps constant,
délégué au store). `require_admin` gate les routes réservées au rôle admin."""

from __future__ import annotations

from fastapi import HTTPException, Request

from sporia.users import accounts


def verify(email: str, password: str) -> dict | None:
    """Vérifie l'email + mot de passe via le store SQLite. Renvoie {username,name,role} ou None."""
    return accounts.verify_password(email, password)


def require_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    return user


def require_admin(request: Request) -> dict:
    """Comme require_user, mais restreint aux comptes role=admin (rôle porté par la session)."""
    user = require_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Réservé à l'administrateur.")
    return user
