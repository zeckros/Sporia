"""Overlay « radar » — extrait de champi_core (iso-comportement)."""

from __future__ import annotations

import datetime
import hashlib
import math
import threading

import matplotlib.pyplot as plt
import numpy as np
from rasterio.crs import CRS as RioCRS
from rasterio.warp import Resampling as RioResampling
from rasterio.warp import reproject as rio_reproject

from sporia.config import settings
from sporia.domain.species import MUSHROOMS
from sporia.domain.suitability import RADAR_VMAX
from sporia.enrich import forest as mmap
from sporia.enrich import fruiting_live
from sporia.geo.rasters import (
    _forest_mask,
    _grid_ref,
    _grid_ref_geo,
    _mask_to_france,
    _reproject_to_3857,
    _reproject_to_grid,
    _tile_bbox_3857,
)
from sporia.geo.render import _blank_tile, _bust, _save_png
from sporia.overlays.fruiting import fruiting_models

DATA_DIR = settings.output_tiff_dir
OVERLAY_DIR = settings.overlay_dir
MASK_CACHE = settings.data_cache_dir


_YLGN_LUT = (plt.cm.YlGn(np.linspace(0.0, 1.0, 256))[:, :3] * 255).astype(np.uint8)  # [256,3]

_FOREST_TILE_DIR = MASK_CACHE / "foresttiles"  # cache permanent (couche statique)

_RADAR_TILE_DIR = MASK_CACHE / "radartiles"  # cache par jour/sélection

FOREST_CRISP_ZOOM = 0

FOREST_MAX_Z = 13  # zoom natif max pré-stocké (cf. app.js maxNativeZoom)

FOREST_MASK_MIN = 0.05  # densité forêt (BD Forêt 1 km) mini pour AFFICHER le radar sur la maille

_radar_grid_cache: dict = {}

_radar_grid_lock = threading.Lock()


def render_radar_overlay(species_list, ref_date: str | None = None):
    """« Radar à champignons » : carte agrégée OÙ (SDM habitat, arbre-hôte) × QUAND
    (météo du moment) sur les espèces sélectionnées. Remplace l'ancienne favorabilité.
    Renvoie {url, bounds, species, date, legend} ou None."""
    grid, used, date = fruiting_live.radar(species_list, ref_date, params=_radar_species_params())
    if grid is None:
        return None
    ref = _grid_ref()
    if ref is None:
        return None
    noms = {m["latin"]: m["nom"] for m in MUSHROOMS}
    species = [noms.get(s, s) for s in used]

    # Masque forêt HAUTE RÉSOLUTION (BD Forêt®, baké) : le radar épouse les contours réels
    # des forêts (même source que le calque forêt). Échelle ABSOLUE (RADAR_VMAX). Rendu mis
    # en cache (clé = date + espèces) car plus lourd. Les indices fiche/spots ne sont PAS
    # masqués (requêtes ponctuelles sur la grille brute).
    fm = _forest_mask()
    if fm is not None:
        mask, (west, south, east, north), bounds = fm
        H, W = mask.shape
        key = hashlib.md5(("radarF" + str(date) + ",".join(sorted(used))).encode()).hexdigest()[:12]
        out = OVERLAY_DIR / f"radar_{key}.png"
        if not out.exists():
            val = _reproject_to_grid(grid, str(ref), west, south, east, north, W, H)
            norm = np.clip(np.nan_to_num(val, nan=0.0) / RADAR_VMAX, 0.0, 1.0).astype(np.float32)
            finite = np.isfinite(val) & mask  # vert seulement sur forêt ET habitat présent
            del val
            img = np.zeros((H, W, 4), np.uint8)
            img[..., :3] = _YLGN_LUT[(norm * 255).astype(np.uint8)]
            img[..., 3] = (np.clip(np.where(finite, 0.15 + 0.8 * norm, 0.0), 0, 1) * 255).astype(
                np.uint8
            )
            del norm, finite
            _save_png(
                img, out.name, max_px=max(H, W), optimize=False
            )  # grande image → encodage rapide
            del img
        return {
            "url": _bust(out.name),
            "bounds": bounds,
            "date": date,
            "species": species,
            "legend": {"species": species},
        }

    # --- Repli (masque pas encore baké) : rendu 1 km masqué par la densité forêt 1 km ---
    dens = mmap.load_forest_density()
    if dens is not None and dens.shape == grid.shape:
        grid = np.where(dens >= FOREST_MASK_MIN, grid, np.nan).astype(np.float32)
    arr, bounds = _reproject_to_3857(
        np.ascontiguousarray(_mask_to_france(grid, ref)), str(ref), resampling=RioResampling.nearest
    )
    finite = np.isfinite(arr)
    if not finite.any():
        return None
    norm = np.clip(np.where(finite, arr, 0.0) / RADAR_VMAX, 0.0, 1.0)
    rgba = plt.cm.YlGn(norm)
    img = np.zeros((arr.shape[0], arr.shape[1], 4), np.uint8)
    img[..., :3] = (rgba[..., :3] * 255).astype(np.uint8)
    img[..., 3] = (np.clip(np.where(finite, 0.15 + 0.8 * norm, 0.0), 0, 1) * 255).astype(np.uint8)
    key = hashlib.md5(("radar" + str(date) + ",".join(sorted(used))).encode()).hexdigest()[:12]
    _save_png(img, f"radar_{key}.png")
    return {
        "url": _bust(f"radar_{key}.png"),
        "bounds": bounds,
        "date": date,
        "species": species,
        "legend": {"species": species},
    }


def _forest_tile_alpha(z, x, y):
    """Alpha 256×256 de la tuile BD Forêt WMTS (z/x/y) = masque forêt. Cache disque
    permanent (couche statique). None si hors couverture / indisponible.

    Stockage : on ne garde que le CANAL ALPHA (PNG mode 'L', forêt/pas forêt) — pas les
    couleurs des 32 types de forêt → cache ~6× plus léger (cf. scripts/bake_forest_tiles.py).
    Lecture rétro-compatible avec d'anciennes tuiles RGBA."""
    from PIL import Image

    fp = _FOREST_TILE_DIR / str(z) / str(x) / f"{y}.png"
    if not fp.exists():
        import io

        import requests

        url = (
            "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
            "&LAYER=LANDCOVER.FORESTINVENTORY.V2&STYLE=normal&TILEMATRIXSET=PM"
            f"&FORMAT=image/png&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}"
        )
        try:
            r = requests.get(url, timeout=20)
        except Exception:
            return None
        if r.status_code != 200 or "image" not in r.headers.get("content-type", ""):
            return None
        try:
            alpha = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGBA"))[..., 3]
        except Exception:
            return None
        fp.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(alpha, "L").save(fp, format="PNG", optimize=True)  # alpha seul
        return alpha
    try:
        im = Image.open(fp)
        # nouveau format = 'L' (alpha seul) ; ancien = RGBA → on prend le canal alpha.
        return np.asarray(im) if im.mode == "L" else np.asarray(im.convert("RGBA"))[..., 3]
    except Exception:
        return None


def _forest_alpha_from_mask(z, x, y):
    """Alpha 256×256 (uint8, 0/255) de la tuile z/x/y dérivée du MASQUE FORÊT BAKÉ en
    mémoire (BD Forêt®, même source que `_forest_tile_alpha`) — SANS aucun appel réseau.
    Renvoie None si le masque n'est pas baké ou si la tuile est hors couverture.

    C'est le chemin rapide du « Radar à champignons » : clipper chaque tuile au contour
    forêt sans aller chercher la tuile WMTS de l'IGN (un aller-retour HTTP bloquant par
    tuile, dominant au changement de zoom)."""
    fm = _forest_mask()
    if fm is None:
        return None
    mask, (mw, ms, me, mn), _bounds = fm
    H, W = mask.shape
    px = (me - mw) / W  # taille pixel masque (m, 3857)
    py = (mn - ms) / H
    tw, ts, te, tn = _tile_bbox_3857(z, x, y)
    # Fenêtre du masque couvrant la tuile (+1 px de marge), bornée à la grille.
    c0 = max(0, int(math.floor((tw - mw) / px)) - 1)
    c1 = min(W, int(math.ceil((te - mw) / px)) + 1)
    r0 = max(0, int(math.floor((mn - tn) / py)) - 1)
    r1 = min(H, int(math.ceil((mn - ts) / py)) + 1)
    if c1 <= c0 or r1 <= r0:
        return np.zeros((256, 256), np.uint8)  # hors emprise (océan/étranger) → pas de forêt
    sub = mask[r0:r1, c0:c1]
    if not sub.any():
        return np.zeros((256, 256), np.uint8)  # dans l'emprise mais aucune forêt
    from rasterio.transform import from_bounds as _fb

    sw, se = mw + c0 * px, mw + c1 * px
    sn, ss = mn - r0 * py, mn - r1 * py
    dst = np.zeros((256, 256), np.float32)
    rio_reproject(
        source=np.ascontiguousarray(sub, np.float32),
        destination=dst,
        src_transform=_fb(sw, ss, se, sn, sub.shape[1], sub.shape[0]),
        src_crs=RioCRS.from_epsg(3857),
        dst_transform=_fb(tw, ts, te, tn, 256, 256),
        dst_crs=RioCRS.from_epsg(3857),
        resampling=RioResampling.nearest,
    )
    return (dst > 0.5).astype(np.uint8) * 255


def _radar_grid(species_list, ref_date=None):
    """Grille radar 1 km (habitat×pousse), mise en cache mémoire par (date, espèces).

    Verrou : au 1er chargement, le navigateur tire des dizaines de tuiles d'un coup, qui
    réclament toutes la MÊME grille (non encore en cache). Sans verrou, chaque requête la
    recalcule (~14 s × espèces) en parallèle → threadpool saturé, serveur figé. Le verrou
    sérialise : un seul thread bâtit la grille, les autres attendent puis lisent le cache."""
    key = (ref_date or "_today", tuple(sorted(species_list)))
    cached = _radar_grid_cache.get(key)
    if cached is not None:
        return cached
    with _radar_grid_lock:
        if key not in _radar_grid_cache:  # double-check après acquisition
            if len(_radar_grid_cache) > 8:
                _radar_grid_cache.clear()
            _radar_grid_cache[key] = fruiting_live.radar(
                species_list, ref_date, params=_radar_species_params()
            )
        return _radar_grid_cache[key]


def radar_tile_png(z, x, y, species_list, ref_date=None) -> bytes:
    """PNG 256×256 d'une tuile radar (cache disque). Transparent si rien à montrer."""
    z, x, y = int(z), int(x), int(y)
    if not (0 <= z <= 19 and 0 <= x < 2**z and 0 <= y < 2**z):
        return _blank_tile()
    grid, used, date = _radar_grid(species_list, ref_date)
    if grid is None or not used:
        return _blank_tile()
    sphash = hashlib.md5(",".join(sorted(used)).encode()).hexdigest()[:10]
    cache = _RADAR_TILE_DIR / str(date).replace("-", "") / sphash / str(z) / str(x) / f"{y}.png"
    if cache.exists():
        return cache.read_bytes()
    ref = _grid_ref()
    if ref is None:
        return _blank_tile()
    # Contour forêt — stratégie HYBRIDE :
    #  • zooms larges (z < FOREST_CRISP_ZOOM) : masque baké en mémoire (rapide, zéro réseau ;
    #    à ces échelles 400 m << 1 px de tuile → bordure visuellement identique au WMTS).
    #  • zooms serrés (z ≥ FOREST_CRISP_ZOOM) : tuile BD Forêt WMTS pixel-exacte (contours nets
    #    « comme avant », là où l'aspect carré du masque deviendrait visible). Réseau au 1er
    #    affichage puis cache disque permanent. Repli sur le masque si WMTS indisponible.
    if z >= FOREST_CRISP_ZOOM:
        alpha_forest = _forest_tile_alpha(z, x, y)
        if alpha_forest is None:
            alpha_forest = _forest_alpha_from_mask(z, x, y)
    else:
        alpha_forest = _forest_alpha_from_mask(z, x, y)
        if alpha_forest is None:
            alpha_forest = _forest_tile_alpha(z, x, y)
    if alpha_forest is None or not bool((alpha_forest > 10).any()):
        return _blank_tile()  # hors forêt → rien (pas de cache)
    from rasterio.transform import from_bounds as _fb

    west, south, east, north = _tile_bbox_3857(z, x, y)
    src_crs, src_tr = _grid_ref_geo(str(ref))
    val = np.full((256, 256), np.nan, np.float32)
    rio_reproject(
        source=np.ascontiguousarray(grid, np.float32),
        destination=val,
        src_transform=src_tr,
        src_crs=src_crs,
        dst_transform=_fb(west, south, east, north, 256, 256),
        dst_crs=RioCRS.from_epsg(3857),
        resampling=RioResampling.bilinear,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )
    finite = np.isfinite(val) & (alpha_forest > 10)
    if not bool(finite.any()):
        png = _blank_tile()
    else:
        norm = np.clip(np.nan_to_num(val, nan=0.0) / RADAR_VMAX, 0.0, 1.0).astype(np.float32)
        img = np.zeros((256, 256, 4), np.uint8)
        img[..., :3] = _YLGN_LUT[(norm * 255).astype(np.uint8)]
        img[..., 3] = (np.clip(np.where(finite, 0.15 + 0.8 * norm, 0.0), 0, 1) * 255).astype(
            np.uint8
        )
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.fromarray(img, "RGBA").save(buf, format="PNG", optimize=False, compress_level=2)
        png = buf.getvalue()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(png)
    return png


def radar_tile_species(species_list, ref_date=None):
    """Noms FR des espèces réellement affichées (en saison + servies) — pour la légende."""
    served = set(fruiting_models())
    if ref_date:
        try:
            month = datetime.datetime.strptime(str(ref_date), "%Y%m%d").month
        except Exception:
            month = datetime.date.today().month
    else:
        month = datetime.date.today().month
    noms = {m["latin"]: m["nom"] for m in MUSHROOMS}
    mset = {m["latin"]: set(m["months"]) for m in MUSHROOMS}
    return [noms.get(s, s) for s in species_list if s in served and month in mset.get(s, set())]


def _radar_species_params():
    """Paramètres mycologiques par espèce (depuis MUSHROOMS) passés au radar pour
    moduler la fenêtre de pousse : délai post-pluie, cumul mini, plage de température."""
    return {
        m["latin"]: {
            "rain_lag": tuple(m["rain_lag"]),
            "rain_min": m["rain_min"],
            "t_min": m["t_min"],
            "t_max": m["t_max"],
            "months": list(m["months"]),
        }
        for m in MUSHROOMS
    }
