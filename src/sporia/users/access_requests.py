"""Demandes d'accès / contact (site sur invitation) — stockage JSON.

data/access_requests.json : liste de { id, name, email, message, created }.
Écriture atomique + verrou. L'admin consulte via GET /api/access-requests."""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from sporia.config import settings

_LOCK = threading.Lock()
MAX_REQUESTS = 200  # garde-fou anti-abus (FIFO)


def _path() -> Path:
    return settings.data_dir / "access_requests.json"


def _load() -> list:
    p = _path()
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return d if isinstance(d, list) else []
        except Exception:
            pass
    return []


def _save(reqs: list) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(reqs, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)  # écriture atomique


def add_request(name: str, email: str, message: str) -> dict:
    """Enregistre une demande et renvoie l'objet créé. Capé à MAX_REQUESTS (FIFO)."""
    req = {
        "id": uuid.uuid4().hex[:12],
        "name": (name or "").strip()[:80],
        "email": (email or "").strip()[:120],
        "message": (message or "").strip()[:2000],
        "created": int(time.time()),
    }
    with _LOCK:
        reqs = _load()
        reqs.append(req)
        if len(reqs) > MAX_REQUESTS:
            del reqs[0 : len(reqs) - MAX_REQUESTS]
        _save(reqs)
    return req


def list_requests() -> list:
    """Toutes les demandes (les plus récentes en dernier)."""
    return _load()
