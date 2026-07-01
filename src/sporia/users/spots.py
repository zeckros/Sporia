"""Spots enregistrés par compte (« mes coins à champignons ») — stockage JSON.

data/user_spots.json : { "<username>": {"spots": [ {id, name, lat, lon, created}, … ]}, … }.
Découplé de config.yaml, écriture atomique, verrou."""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from sporia.config import settings

_LOCK = threading.Lock()
MAX_SPOTS = 50  # garde-fou anti-abus par compte


def _path() -> Path:
    return settings.data_dir / "user_spots.json"


def _load_all() -> dict:
    p = _path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
    return {}


def _save_all(allp: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(allp, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)  # écriture atomique


def list_spots(username: str) -> list[dict]:
    """Spots enregistrés du compte (liste, éventuellement vide)."""
    entry = _load_all().get(username or "", {})
    sp = entry.get("spots")
    return list(sp) if isinstance(sp, list) else []


def add_spot(username: str, lat: float, lon: float, name: str) -> dict:
    """Ajoute un spot et renvoie l'objet créé (avec id). Capé à MAX_SPOTS (FIFO)."""
    spot = {
        "id": uuid.uuid4().hex[:12],
        "name": (name or "").strip()[:60] or f"Spot {lat:.3f}, {lon:.3f}",
        "lat": round(float(lat), 5),
        "lon": round(float(lon), 5),
        "created": int(time.time()),
    }
    with _LOCK:
        allp = _load_all()
        spots = allp.setdefault(username, {}).setdefault("spots", [])
        spots.append(spot)
        if len(spots) > MAX_SPOTS:
            del spots[0 : len(spots) - MAX_SPOTS]
        _save_all(allp)
    return spot


def rename_spot(username: str, spot_id: str, name: str) -> bool:
    """Renomme un spot par id. Renvoie True si trouvé/renommé."""
    new = (name or "").strip()[:60]
    if not new:
        return False
    with _LOCK:
        allp = _load_all()
        spots = allp.get(username, {}).get("spots")
        if not isinstance(spots, list):
            return False
        for s in spots:
            if s.get("id") == spot_id:
                s["name"] = new
                _save_all(allp)
                return True
        return False


def delete_spot(username: str, spot_id: str) -> bool:
    """Supprime un spot par id. Renvoie True si un spot a été retiré."""
    with _LOCK:
        allp = _load_all()
        spots = allp.get(username, {}).get("spots")
        if not isinstance(spots, list):
            return False
        kept = [s for s in spots if s.get("id") != spot_id]
        if len(kept) == len(spots):
            return False
        allp[username]["spots"] = kept
        _save_all(allp)
    return True
