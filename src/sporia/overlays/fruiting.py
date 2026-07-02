"""Overlay « fruiting » — extrait de champi_core (iso-comportement)."""

from __future__ import annotations

import matplotlib.pyplot as plt

from sporia.config import settings
from sporia.enrich import fruiting_live
from sporia.geo.render import _render_grid_overlay

DATA_DIR = settings.output_tiff_dir
OVERLAY_DIR = settings.overlay_dir
MASK_CACHE = settings.data_cache_dir

EXCLUDED_FROM_MODELING = {"Morchella esculenta"}


def fruiting_models():
    """Espèces disposant d'un modèle de fructification (point #4), hors espèces
    exclues de la modélisation."""
    return [s for s in fruiting_live.available_models() if s not in EXCLUDED_FROM_MODELING]


def render_fruiting_overlay(species: str, ref_date: str | None = None):
    """Overlay « pousse en ce moment » : probabilité de fructification du jour
    pour une espèce (modèle météo-dépendant appliqué aux ~21 derniers jours).
    Renvoie {url, bounds, legend, species, date} ou None."""
    grid, date_iso = fruiting_live.score_species(species, ref_date)
    if grid is None:
        return None
    safe = species.replace(" ", "_")
    res = _render_grid_overlay(grid, f"fruiting_{safe}.png", plt.cm.YlOrRd, 0.0, 1.0)
    if res is None:
        return None
    res["legend"] = {"vmin": 0, "vmax": 100, "unit": "% (indice de pousse)", "cmap": "YlOrRd"}
    res["species"] = species
    res["date"] = date_iso
    return res
