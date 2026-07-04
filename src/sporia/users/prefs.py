"""Préférences utilisateur (sélection de champignons) — stockage JSON par compte.

Fichier data/user_prefs.json : { "<username>": {"species": ["<latin>", …]}, … }.
Découplé de config.yaml (identifiants). Absence de préférence → None (= toutes les espèces)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from sporia.config import settings

_LOCK = threading.Lock()


def _path() -> Path:
    return settings.data_dir / "user_prefs.json"


def _load_all() -> dict:
    p = _path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
    return {}


def get_species(username: str) -> list[str] | None:
    """Latins sélectionnés par l'utilisateur, ou None si aucune préférence."""
    entry = _load_all().get(username or "", {})
    sp = entry.get("species")
    return list(sp) if isinstance(sp, list) else None


def set_species(username: str, species: list[str]) -> list[str]:
    """Enregistre la sélection (liste de latins) pour l'utilisateur."""
    species = list(dict.fromkeys(species))  # dédoublonne en gardant l'ordre
    with _LOCK:
        allp = _load_all()
        allp.setdefault(username, {})["species"] = species
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(allp, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)  # écriture atomique
    return species


def delete_user(username: str) -> None:
    """Effacement RGPD : retire les préférences du compte (no-op si absentes)."""
    with _LOCK:
        allp = _load_all()
        if username in allp:
            del allp[username]
            p = _path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(allp, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(p)
