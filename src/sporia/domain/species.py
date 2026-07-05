"""Espèces modélisées — chargées depuis data/species.yaml, converties au format legacy
(months: set ; rain_lag/ph_opt/alt_opt: tuple) pour une compatibilité stricte."""

from __future__ import annotations

from importlib import resources

import yaml

_PAIR_FIELDS = ("rain_lag", "ph_opt", "alt_opt")


def _load() -> list[dict]:
    src = resources.files("sporia").joinpath("data", "species.yaml")
    with src.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    out: list[dict] = []
    for entry in raw:
        m = dict(entry)
        m["months"] = set(m["months"])
        for k in _PAIR_FIELDS:
            if k in m and m[k] is not None:
                m[k] = tuple(m[k])
        out.append(m)
    return out


MUSHROOMS: list[dict] = _load()

_GUILD_DEFAULT = "ecto"


def guild_of(latin: str) -> str:
    """Guilde de l'espèce ('ecto' | 'open' | 'sapro'), 'ecto' par défaut si absente
    (rétrocompatibilité : une espèce sans champ `guild` garde le comportement complet)."""
    for m in MUSHROOMS:
        if m["latin"] == latin:
            return m.get("guild", _GUILD_DEFAULT)
    return _GUILD_DEFAULT


# Variables conservées pour la guilde « open » (en plus de tout `lc_*` et `clim_*`).
# Retire implicitement forest_density, host_*, edge_density, twi, tpi, slope_dem, lat/lon :
# structure et hydrologie forestières = bruit + sur-apprentissage pour une prairie.
_OPEN_HABITAT_KEEP = frozenset(
    {
        "ph",
        "clay",
        "sand",
        "silt",  # texture du sol
        "soc",
        "cec",  # fertilité
        "dist_water",  # humidité (proximité de l'eau)
        "altitude",
        "slope",
        "northness",  # relief
    }
)


def _keep_open(feat: str) -> bool:
    return feat in _OPEN_HABITAT_KEEP or feat.startswith("lc_") or feat.startswith("clim_")


def habitat_feature_subset(feats: list[str], latin: str) -> list[str]:
    """Sous-ensemble de variables d'habitat propre à la guilde (ordre de `feats` préservé).
    'ecto' → jeu complet. 'sapro'/'open' → host_* retiré. 'open' → en plus, restreint au
    jeu « milieu ouvert » (_keep_open)."""
    g = guild_of(latin)
    if g == "ecto":
        return list(feats)
    out = [f for f in feats if not f.startswith("host_")]
    if g == "open":
        out = [f for f in out if _keep_open(f)]
    return out
