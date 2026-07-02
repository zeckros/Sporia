"""Overlay « soil » — extrait de champi_core (iso-comportement)."""

from __future__ import annotations

import datetime

import matplotlib.pyplot as plt
import numpy as np
from rasterio.warp import Resampling as RioResampling

from sporia.config import settings
from sporia.enrich import forest as mmap
from sporia.enrich import soil_static as soil_data
from sporia.geo.rasters import (
    _grid_ref,
    _mask_to_france,
    _reproject_to_3857,
)
from sporia.geo.render import _bust, _hex_to_rgb, _render_grid_overlay, _save_png
from sporia.places import available_dates

DATA_DIR = settings.output_tiff_dir
OVERLAY_DIR = settings.overlay_dir
MASK_CACHE = settings.data_cache_dir

SOIL_COLORS = {
    "sand": "#efd081",
    "loamy_sand": "#e4c172",
    "sandy_loam": "#d3ad63",
    "loam": "#b98f50",
    "silt_loam": "#aac06a",
    "silt": "#c7da8b",
    "sandy_clay_loam": "#c08a54",
    "clay_loam": "#a9743f",
    "silty_clay_loam": "#8f9a4f",
    "sandy_clay": "#b1623a",
    "silty_clay": "#8c5a40",
    "clay": "#7a4630",
}


def render_soil_moisture_overlay(ref_date: str | None = None):
    """Overlay humidité du sol (raster SM le plus récent). Dégradé sec→humide."""
    ref = (
        datetime.datetime.strptime(ref_date, "%Y%m%d").date()
        if ref_date
        else (available_dates()[-1] if available_dates() else None)
    )
    if ref is None:
        return None
    grid = mmap._latest_soil_grid(str(DATA_DIR), "SM", ref)
    res = _render_grid_overlay(grid, "soil_moisture.png", plt.cm.BrBG, 0.05, 0.40)
    if res:
        res["legend"] = {"vmin": 5, "vmax": 40, "unit": "% vol.", "cmap": "BrBG"}
    return res


def render_soil_overlay():
    """Overlay « type de sol » = classes texturales USDA (SoilGrids). Couche
    statique → PNG stable. Renvoie {url, bounds, legend:[{key,label,color}]} ou None."""
    grids = soil_data.load_soil_static()
    if grids is None:
        return None
    ref = _grid_ref()
    if ref is None:
        return None

    idx = soil_data.texture_class_grid(grids["sand"], grids["silt"], grids["clay"])
    idx_f = idx.astype(np.float32)
    idx_f[idx < 0] = np.nan
    idx_f = _mask_to_france(idx_f, ref)  # clippe à la France (pas de pays voisins)
    arr, bounds = _reproject_to_3857(
        np.ascontiguousarray(idx_f), str(ref), resampling=RioResampling.nearest
    )

    h, w = arr.shape
    img = np.zeros((h, w, 4), np.uint8)
    present = []
    for n, key in enumerate(soil_data.CLASS_ORDER):
        mask = np.abs(arr - n) < 0.5
        if mask.any():
            r, g, b = _hex_to_rgb(SOIL_COLORS[key])
            img[mask, 0], img[mask, 1], img[mask, 2], img[mask, 3] = r, g, b, 200
            present.append(key)
    from PIL import Image as _Image

    _save_png(img, "soil_texture.png", resample=_Image.NEAREST)
    legend = [
        {"key": k, "label": soil_data.TEXTURE_FR[k], "color": SOIL_COLORS[k]}
        for k in soil_data.CLASS_ORDER
        if k in present
    ]
    return {"url": _bust("soil_texture.png"), "bounds": bounds, "legend": legend}
