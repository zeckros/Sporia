"""Fiabilité de la carte d'habitat (SDM) par espèce, depuis data/species_metrics.yaml.
Ne servir que les espèces au Boyce habitat >= seuil (les autres induisent l'utilisateur
en erreur : ex. Calocybe gambosa Boyce -0.19, ou morille sans modèle)."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

import yaml

DEFAULT_THRESHOLD = 0.10


@lru_cache(maxsize=1)
def habitat_boyce() -> dict[str, float]:
    src = resources.files("sporia").joinpath("data", "species_metrics.yaml")
    with src.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return {sp: float(v["boyce"]) for sp, v in raw.items() if isinstance(v, dict) and "boyce" in v}


def is_reliable_habitat(latin: str, threshold: float = DEFAULT_THRESHOLD) -> bool:
    """True si l'espèce a un modèle d'habitat fiable (Boyce présent ET >= seuil).
    Absent (pas de modèle) ou Boyce < seuil → False (espèce non servie)."""
    b = habitat_boyce().get(latin)
    return b is not None and b >= threshold
