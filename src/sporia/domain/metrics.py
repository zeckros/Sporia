"""Fiabilité de la carte d'habitat (SDM) par espèce, depuis data/species_metrics.yaml.

Le gating et les paliers de confiance sont pilotés par l'**AUC** (discrimination), et non
plus par le Boyce : l'AUC est stable (indépendante de la taille d'échantillon), alors que le
Boyce — même stabilisé par CV répétée — reste dépendant de N entre modèles (il se gonfle avec
le nombre de présences, cf. courbe d'apprentissage transfrontalière). Le Boyce reste stocké à
titre informatif dans le YAML."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

import yaml

# Seuils AUC (0.5 = hasard). Servie >= 0.65 ; palier « bonne » >= 0.73 ; « élevée » >= 0.80.
AUC_SERVED = 0.65
AUC_BONNE = 0.73
AUC_ELEVEE = 0.80


@lru_cache(maxsize=1)
def _habitat_raw() -> dict[str, dict]:
    src = resources.files("sporia").joinpath("data", "species_metrics.yaml")
    with src.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return {sp: v for sp, v in raw.items() if isinstance(v, dict) and "auc" in v}


def habitat_boyce() -> dict[str, float]:
    """Boyce moyen par espèce (informatif ; consommé par des tests / autres appelants)."""
    return {sp: float(v["boyce"]) for sp, v in _habitat_raw().items() if "boyce" in v}


def habitat_auc() -> dict[str, float]:
    """AUC d'habitat par espèce (métrique de gating)."""
    return {sp: float(v["auc"]) for sp, v in _habitat_raw().items()}


def _tier_auc(auc: float) -> str:
    if auc >= AUC_ELEVEE:
        return "élevée"
    if auc >= AUC_BONNE:
        return "bonne"
    return "modérée"


def _auc_of(latin: str) -> float | None:
    v = _habitat_raw().get(latin)
    return float(v["auc"]) if v is not None else None


def is_reliable_habitat(latin: str, threshold: float = AUC_SERVED) -> bool:
    """True si l'AUC d'habitat >= seuil (défaut 0.65). Espèce absente → False."""
    auc = _auc_of(latin)
    return auc is not None and auc >= threshold


def confidence_tier(latin: str) -> str:
    """Palier de confiance sur l'AUC : « élevée » (>= 0.80), « bonne » (>= 0.73), sinon
    « modérée » (y compris AUC absente)."""
    auc = _auc_of(latin)
    return _tier_auc(auc) if auc is not None else "modérée"
