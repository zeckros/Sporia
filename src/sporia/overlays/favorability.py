"""Overlay « favorability » — extrait de champi_core (iso-comportement)."""

from __future__ import annotations

import hashlib

import matplotlib.pyplot as plt
import numpy as np

from sporia.config import settings
from sporia.domain.species import MUSHROOMS
from sporia.enrich import forest as mmap
from sporia.geo.rasters import (
    _reproject_to_3857,
)
from sporia.geo.render import _bust, _save_png
from sporia.places import available_dates

DATA_DIR = settings.output_tiff_dir
OVERLAY_DIR = settings.overlay_dir
MASK_CACHE = settings.data_cache_dir

FOREST_DISPLAY_MIN = 0.05  # plancher : en dessous, rien n'est affiché (strict)

FOREST_DISPLAY_FULL = 0.40  # au-dessus, opacité maximale


def render_favorability_overlay(ref_date: str, species: list[str] | None = None):
    """Overlay « zones à champignons ». `species` = sous-ensemble de noms latins
    à considérer (sinon toutes). Renvoie {url, bounds, season_species, …} ou None."""
    dates = [d.strftime("%Y%m%d") for d in available_dates()]
    sel = MUSHROOMS
    if species:
        wanted = set(species)
        sel = [m for m in MUSHROOMS if m["latin"] in wanted] or MUSHROOMS
    res = mmap.compute_favorability(sel, ref_date, dates, str(DATA_DIR))
    if res is None:
        return None
    fav = np.asarray(res["fav"], dtype=np.float32)
    ref = DATA_DIR / f"RR_{ref_date}.tif"
    if not ref.exists():
        return None
    arr_final, bounds = _reproject_to_3857(fav, str(ref))
    favc = np.where(np.isnan(arr_final), 0.0, arr_final)
    norm = np.clip(favc / 0.6, 0, 1)
    rgba = plt.cm.YlGn(norm)
    # Alpha calé sur la couche forêt : opacité ∝ densité BD Forêt, et STRICTEMENT
    # nulle hors forêt. La densité est reprojetée dans le MÊME espace 3857 que la
    # favorabilité → bords alignés, aucune bavure. Bois clairsemé = léger, forêt
    # dense = plein ; pas de forêt = rien.
    density = res.get("density")
    if density is not None:
        den_final, _ = _reproject_to_3857(
            np.ascontiguousarray(np.asarray(density, np.float32)), str(ref)
        )
        denc = np.where(np.isnan(den_final), 0.0, den_final)
        forest_alpha = np.clip(
            (denc - FOREST_DISPLAY_MIN) / (FOREST_DISPLAY_FULL - FOREST_DISPLAY_MIN), 0.0, 1.0
        )
    else:
        forest_alpha = (favc > 0).astype(np.float32)
    # opacité = présence forêt × favorabilité : bois peu favorables = très léger,
    # coins favorables = bien marqués ; hors forêt = 0 (strict).
    alpha = forest_alpha * (0.2 + 0.75 * norm)
    img = np.zeros((rgba.shape[0], rgba.shape[1], 4), np.uint8)
    img[..., :3] = (rgba[..., :3] * 255).astype(np.uint8)
    img[..., 3] = (np.clip(alpha, 0, 1) * 255).astype(np.uint8)
    # le hash inclut la sélection d'espèces → un PNG distinct par sélection
    spec_key = ",".join(sorted(species)) if species else "all"
    key = hashlib.md5(("fav" + ref_date + spec_key).encode()).hexdigest()[:12]
    _save_png(img, f"fav_{key}.png")
    return {
        "url": _bust(f"fav_{key}.png"),
        "bounds": bounds,
        "season_species": res.get("season_species", []),
        "has_weather": res.get("has_weather", False),
        "has_soil": res.get("has_soil", False),
        "has_terrain": res.get("has_terrain", False),
    }
