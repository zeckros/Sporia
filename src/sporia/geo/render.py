"""Rendu PNG des overlays — primitives (sauvegarde, colormap→RGBA, cache-bust,
tuile vierge, couleur hex). Extrait de champi_core (iso-comportement)."""

from __future__ import annotations

import matplotlib
import numpy as np

matplotlib.use("Agg")

from sporia.config import settings  # noqa: E402
from sporia.geo.rasters import (  # noqa: E402
    _grid_ref,
    _mask_to_france,
    _reproject_to_3857,
)

OVERLAY_DIR = settings.overlay_dir
_blank_png_bytes = None


def _save_png(rgba_uint8, fname, resample=None, max_px=2048, optimize=True, compress_level=6):
    from PIL import Image

    if resample is None:
        resample = Image.LANCZOS
    im = Image.fromarray(rgba_uint8, mode="RGBA")
    w, h = im.size
    if max(w, h) > max_px:
        s = max_px / max(w, h)
        im = im.resize((max(1, int(w * s)), max(1, int(h * s))), resample)
    # optimize=True force un encodage lent (utile pour les petits overlays stables) ;
    # on le désactive pour les grands rendus (radar) où la vitesse prime.
    im.save(OVERLAY_DIR / fname, format="PNG", optimize=optimize, compress_level=compress_level)
    return f"/overlays/{fname}"


def _bust(fname: str) -> str:
    """URL d'overlay avec cache-busting (?v=mtime) pour les noms de fichiers
    stables (sol/humidité/altitude/exposition) — évite un PNG périmé en cache."""
    import os

    try:
        return f"/overlays/{fname}?v={int(os.path.getmtime(OVERLAY_DIR / fname))}"
    except Exception:
        return f"/overlays/{fname}"


def _render_grid_overlay(grid2d, fname, cmap, vmin, vmax, base_alpha=0.82):
    """Reprojette une grille continue alignée (NaN → transparent) et écrit un PNG
    overlay (busté), clippé à la France. Renvoie {url, bounds} ou None."""
    if grid2d is None:
        return None
    ref = _grid_ref()
    if ref is None:
        return None
    arr, bounds = _reproject_to_3857(np.ascontiguousarray(_mask_to_france(grid2d, ref)), str(ref))
    nan = np.isnan(arr)
    span = (vmax - vmin) if vmax > vmin else 1.0
    norm = np.clip((arr - vmin) / span, 0.0, 1.0)
    norm = np.where(nan, 0.0, norm)
    rgba = cmap(norm)
    img = np.zeros((arr.shape[0], arr.shape[1], 4), np.uint8)
    img[..., :3] = (rgba[..., :3] * 255).astype(np.uint8)
    img[..., 3] = np.where(nan, 0, int(base_alpha * 255)).astype(np.uint8)
    _save_png(img, fname)
    return {"url": _bust(fname), "bounds": bounds}


def _blank_tile() -> bytes:
    global _blank_png_bytes
    if _blank_png_bytes is None:
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGBA", (256, 256), (0, 0, 0, 0)).save(buf, format="PNG")
        _blank_png_bytes = buf.getvalue()
    return _blank_png_bytes


def _hex_to_rgb(h: str):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
