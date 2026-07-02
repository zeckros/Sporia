"""Overlay « terrain » — extrait de champi_core (iso-comportement)."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np

from sporia.config import settings
from sporia.enrich import terrain as terrain_data
from sporia.geo.render import _render_grid_overlay

DATA_DIR = settings.output_tiff_dir
OVERLAY_DIR = settings.overlay_dir
MASK_CACHE = settings.data_cache_dir


def render_altitude_overlay():
    """Overlay altitude / relief (palette hypsométrique)."""
    terr = terrain_data.load_terrain_static()
    if terr is None:
        return None
    res = _render_grid_overlay(terr["altitude"], "altitude.png", plt.cm.terrain, 0.0, 2200.0)
    if res:
        res["legend"] = {"vmin": 0, "vmax": 2200, "unit": "m", "cmap": "terrain"}
    return res


def render_aspect_overlay():
    """Overlay exposition (versants) : sud=chaud (rouge) ↔ nord=frais (bleu).
    Terrain plat (pente faible) → transparent."""
    terr = terrain_data.load_terrain_static()
    if terr is None:
        return None
    north = np.array(terr["northness"], dtype=np.float32)
    north[terr["slope"] < 3.0] = np.nan  # masque les replats
    res = _render_grid_overlay(north, "aspect.png", plt.cm.coolwarm_r, -1.0, 1.0)
    if res:
        res["legend"] = {"south": "Versant sud (chaud)", "north": "Versant nord (frais)"}
    return res
