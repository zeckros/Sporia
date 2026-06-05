#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Préférences utilisateur (sélection de champignons) — stockage JSON par compte.

Fichier data/user_prefs.json : { "<username>": {"species": ["<latin>", …]}, … }.
Découplé de config.yaml (identifiants) : on n'écrit jamais le fichier de secrets.
Absence de préférence → None (= toutes les espèces).
"""
from __future__ import annotations
import json
import threading
from pathlib import Path

PREFS_PATH = Path("data/user_prefs.json")
_LOCK = threading.Lock()


def _load_all() -> dict:
    if PREFS_PATH.exists():
        try:
            return json.loads(PREFS_PATH.read_text(encoding="utf-8")) or {}
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
        PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PREFS_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(allp, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(PREFS_PATH)  # écriture atomique
    return species
