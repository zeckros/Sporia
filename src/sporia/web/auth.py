"""Authentification par comptes (config.yaml, bcrypt) + dépendances FastAPI.

Extrait de server.py. `verify` renvoie None (temps constant, hash leurre) si l'identifiant
est inconnu ou le mot de passe faux. `require_admin` gate les routes réservées à l'admin."""

from __future__ import annotations

from functools import lru_cache

import bcrypt
import yaml
from fastapi import HTTPException, Request

from sporia.config import settings

CONFIG_PATH = settings.base_dir / "config.yaml"

# Hash bcrypt « leurre » : vérifié quand l'identifiant n'existe pas, pour un temps de
# réponse constant (anti-énumération d'identifiants par chronométrage).
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt())


@lru_cache(maxsize=1)
def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def admin_usernames(cfg: dict | None = None) -> set[str]:
    """Comptes avec `role: admin` dans config.yaml."""
    users = (cfg or load_config()).get("credentials", {}).get("usernames", {})
    return {u for u, v in users.items() if isinstance(v, dict) and v.get("role") == "admin"}


def verify(username: str, password: str) -> dict | None:
    users = load_config().get("credentials", {}).get("usernames", {})
    u = users.get(username)
    try:
        if u is None:
            bcrypt.checkpw(password.encode("utf-8"), _DUMMY_HASH)  # temps constant
            return None
        if bcrypt.checkpw(password.encode("utf-8"), u["password"].encode("utf-8")):
            return {"username": username, "name": u.get("name", username)}
    except Exception:
        return None
    return None


def require_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    return user


def require_admin(request: Request) -> dict:
    """Comme require_user, mais restreint aux comptes `role: admin`."""
    user = require_user(request)
    if user.get("username") not in admin_usernames():
        raise HTTPException(status_code=403, detail="Réservé à l'administrateur.")
    return user
