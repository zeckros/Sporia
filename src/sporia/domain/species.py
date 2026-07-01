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
