"""Fiabilité de la carte d'habitat (SDM) par espèce, depuis data/species_metrics.yaml.
Ne servir que les espèces au Boyce habitat >= seuil (les autres induisent l'utilisateur
en erreur : ex. Calocybe gambosa Boyce -0.19, ou morille sans modèle)."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

import yaml

DEFAULT_THRESHOLD = 0.10


@lru_cache(maxsize=1)
def _habitat_raw() -> dict[str, dict]:
    src = resources.files("sporia").joinpath("data", "species_metrics.yaml")
    with src.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return {sp: v for sp, v in raw.items() if isinstance(v, dict) and "boyce" in v}


def habitat_boyce() -> dict[str, float]:
    """Boyce moyen par espèce (rétrocompat : consommé par les tests / autres appelants)."""
    return {sp: float(v["boyce"]) for sp, v in _habitat_raw().items()}


def _conservative(boyce: float, boyce_se: float) -> float:
    """Borne prudente = boyce − erreur-type (arrondi pour éviter le bruit float64)."""
    return round(float(boyce) - float(boyce_se), 6)


def _tier(lower: float) -> str:
    if lower >= 0.50:
        return "élevée"
    if lower >= 0.35:
        return "bonne"
    return "modérée"


def _lower_bound(latin: str) -> float | None:
    """Borne prudente de l'espèce (None si absente ; boyce_se manquant → 0)."""
    v = _habitat_raw().get(latin)
    if v is None:
        return None
    return _conservative(float(v["boyce"]), float(v.get("boyce_se", 0.0)))


def is_reliable_habitat(latin: str, threshold: float = DEFAULT_THRESHOLD) -> bool:
    """True si (boyce − erreur-type) >= seuil. Absent → False."""
    lb = _lower_bound(latin)
    return lb is not None and lb >= threshold


def confidence_tier(latin: str) -> str:
    """Palier de confiance sur la borne prudente : « élevée » (>= 0.50), « bonne »
    (>= 0.35), sinon « modérée » (y compris borne absente)."""
    lb = _lower_bound(latin)
    return _tier(lb) if lb is not None else "modérée"
