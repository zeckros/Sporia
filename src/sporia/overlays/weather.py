"""Overlay « weather » — extrait de champi_core (iso-comportement)."""

from __future__ import annotations

import hashlib

import matplotlib.pyplot as plt
import numpy as np

from sporia.config import settings
from sporia.geo.rasters import (
    _aggregate,
    _france_mask,
    _reproject_to_3857,
)
from sporia.geo.render import _save_png

DATA_DIR = settings.output_tiff_dir
OVERLAY_DIR = settings.overlay_dir
MASK_CACHE = settings.data_cache_dir


def render_weather_overlay(var: str, dates: list[str]):
    """var = 'RR' | 'T'. Renvoie {url, bounds, vmin, vmax, vmean, unit, cmap} ou None."""
    arr_agg = _aggregate(dates, var)
    if arr_agg is None:
        return None
    ref = DATA_DIR / (f"RR_{dates[-1]}.tif" if var == "RR" else f"T_{dates[-1]}.tif")
    mask = _france_mask(str(ref))
    if mask is not None and mask.shape == arr_agg.shape:
        base = arr_agg.mask if hasattr(arr_agg, "mask") else np.zeros_like(arr_agg, bool)
        arr_agg = np.ma.array(arr_agg, mask=np.logical_or(base, ~mask))
    src_arr = (
        arr_agg.filled(np.nan).astype(np.float32)
        if hasattr(arr_agg, "filled")
        else np.asarray(arr_agg, np.float32)
    )

    valid = src_arr[~np.isnan(src_arr)]
    if valid.size == 0:
        return None
    vmin, vmax = float(np.nanpercentile(valid, 2)), float(np.nanpercentile(valid, 98))
    vmean = float(np.nanmean(valid))
    if var == "RR":
        vmin = max(0.0, vmin)
        vmax = max(float(np.nanmax(valid)), vmin + 1.0)

    arr_final, bounds = _reproject_to_3857(src_arr, str(ref))
    cmap = plt.cm.YlGnBu if var == "RR" else plt.cm.RdYlBu_r
    nanmask = np.isnan(arr_final)
    norm = np.clip((arr_final - vmin) / (vmax - vmin if vmax > vmin else 1), 0, 1)
    norm = np.where(nanmask, 0.0, norm)
    rgba = cmap(norm)
    if var == "RR":
        alpha = np.where(nanmask, 0.0, np.where(arr_final >= 0.1, 0.85, 0.0))
    else:
        alpha = np.where(nanmask, 0.0, 0.85)
    img = np.zeros((rgba.shape[0], rgba.shape[1], 4), np.uint8)
    img[..., :3] = (rgba[..., :3] * 255).astype(np.uint8)
    img[..., 3] = (alpha * 255).astype(np.uint8)
    key = f"w{var}{''.join(dates)}{vmin:.2f}{vmax:.2f}"
    url = _save_png(img, f"w_{hashlib.md5(key.encode()).hexdigest()[:12]}.png")
    return {
        "url": url,
        "bounds": bounds,
        "vmin": vmin,
        "vmax": vmax,
        "vmean": vmean,
        "unit": "mm" if var == "RR" else "°C",
        "cmap": "YlGnBu" if var == "RR" else "RdYlBu_r",
    }
