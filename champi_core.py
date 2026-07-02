#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cœur métier ChampiMap — Python pur (AUCUNE dépendance Streamlit).

Réutilisé par le serveur FastAPI (server.py). Reprend la logique de l'ancienne app
Streamlit : accès rasters météo, communes, rendu des overlays (météo + favorabilité
champignons), analyse météo d'un point et associations essence↔champignon (via
mushroom_map.py).

Sorties overlays : PNG écrits dans web/overlays/, servis en statique par FastAPI.
"""
from __future__ import annotations
import hashlib
import datetime
import math
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio import features
from rasterio.crs import CRS as RioCRS
from rasterio.warp import (reproject as rio_reproject, calculate_default_transform,
                           Resampling as RioResampling, transform_bounds as rio_transform_bounds)
import geopandas as gpd
from shapely.geometry import Point, mapping
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import mushroom_map as mmap
import soil_data
import terrain_data
import fruiting_live
from sporia.domain.species import MUSHROOMS
from sporia.domain.suitability import (  # noqa: F401  (re-export legacy facade)
    _ph_match, _altitude_fit_point, _aspect_fit_point, mushroom_suitability,
    _radar_label, RADAR_VMAX, PROPICE_MIN, PROPICE_PCT,
)

from sporia.geo.rasters import (  # noqa: F401  (re-export legacy facade)
    sample_raster, _france_mask, _aggregate, _reproject_to_3857, _reproject_to_grid,
    _forest_mask, _grid_ref, _mask_to_france, _tile_bbox_3857, _grid_ref_geo,
)
from sporia.geo.render import (  # noqa: F401
    _save_png, _bust, _render_grid_overlay, _blank_tile, _hex_to_rgb,
)

from sporia.places import (  # noqa: F401  (re-export legacy facade)
    _static, search_cities, find_commune_at, france_outline_geojson, available_dates,
)

# ===== Configuration =====
DATA_DIR = Path("output/tiff")
VILLES_CSV = "data/villes_france.csv"
COMMUNES_GPKG = "data/communes.gpkg"
OVERLAY_DIR = Path("web/overlays")
OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
MASK_CACHE = Path("data/cache")
MASK_CACHE.mkdir(parents=True, exist_ok=True)

# Affichage des « zones à champignons » calé sur la couche forêt (densité BD Forêt).
# Sous FOREST_MIN : strictement rien (pas de forêt → invisible). Entre FOREST_MIN et
# FOREST_FULL : l'opacité monte avec le couvert (bois clairsemé = léger, forêt dense
# = pleine opacité). Les champignons étant en forêt, l'overlay suit ainsi les bois.
FOREST_DISPLAY_MIN = 0.05   # plancher : en dessous, rien n'est affiché (strict)
FOREST_DISPLAY_FULL = 0.40  # au-dessus, opacité maximale

MONTHS_FR =["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
             "août", "septembre", "octobre", "novembre", "décembre"]



# ===== Données statiques (chargées une fois) =====








# ===== Dates / rasters =====












# Table de couleurs YlGn pré-calculée (uint8) → colorisation des grands rendus sans
# passer par du float64 matplotlib (qui exploserait la mémoire sur une grande image).
_YLGN_LUT = (plt.cm.YlGn(np.linspace(0.0, 1.0, 256))[:, :3] * 255).astype(np.uint8)  # [256,3]

# Masque forêt haute résolution (BD Forêt®, baké par scripts/bake_forest_mask.py).






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
    src_arr = arr_agg.filled(np.nan).astype(np.float32) if hasattr(arr_agg, "filled") else np.asarray(arr_agg, np.float32)

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
    return {"url": url, "bounds": bounds, "vmin": vmin, "vmax": vmax, "vmean": vmean,
            "unit": "mm" if var == "RR" else "°C",
            "cmap": "YlGnBu" if var == "RR" else "RdYlBu_r"}






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
        den_final, _ = _reproject_to_3857(np.ascontiguousarray(np.asarray(density, np.float32)), str(ref))
        denc = np.where(np.isnan(den_final), 0.0, den_final)
        forest_alpha = np.clip((denc - FOREST_DISPLAY_MIN) / (FOREST_DISPLAY_FULL - FOREST_DISPLAY_MIN), 0.0, 1.0)
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
    return {"url": _bust(f"fav_{key}.png"), "bounds": bounds, "season_species": res.get("season_species", []),
            "has_weather": res.get("has_weather", False), "has_soil": res.get("has_soil", False),
            "has_terrain": res.get("has_terrain", False)}






def render_soil_moisture_overlay(ref_date: str | None = None):
    """Overlay humidité du sol (raster SM le plus récent). Dégradé sec→humide."""
    ref = (datetime.datetime.strptime(ref_date, "%Y%m%d").date()
           if ref_date else (available_dates()[-1] if available_dates() else None))
    if ref is None:
        return None
    grid = mmap._latest_soil_grid(str(DATA_DIR), "SM", ref)
    res = _render_grid_overlay(grid, "soil_moisture.png", plt.cm.BrBG, 0.05, 0.40)
    if res:
        res["legend"] = {"vmin": 5, "vmax": 40, "unit": "% vol.", "cmap": "BrBG"}
    return res


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


# Espèces exclues de la MODÉLISATION (habitat SDM + calque « pousse en ce moment »)
# car non modélisables avec nos couches. N'ayant aucun modèle servi, elles ne sont
# PAS affichées dans l'UI (ni sélection « Mes champignons » ni fiche point) ; leur
# entrée MUSHROOMS subsiste uniquement comme métadonnée (host_match, etc.).
#   • Morchella esculenta : écologie de perturbation (ripisylve/frênaies/brûlis/
#     calcaire) absente de nos prédicteurs + biais GBIF urbain ; Boyce reste ≤ 0
#     même après filtre anti-urbain et distance-eau.
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
            finite = np.isfinite(val) & mask          # vert seulement sur forêt ET habitat présent
            del val
            img = np.zeros((H, W, 4), np.uint8)
            img[..., :3] = _YLGN_LUT[(norm * 255).astype(np.uint8)]
            img[..., 3] = (np.clip(np.where(finite, 0.15 + 0.8 * norm, 0.0), 0, 1) * 255).astype(np.uint8)
            del norm, finite
            _save_png(img, out.name, max_px=max(H, W), optimize=False)  # grande image → encodage rapide
            del img
        return {"url": _bust(out.name), "bounds": bounds, "date": date,
                "species": species, "legend": {"species": species}}

    # --- Repli (masque pas encore baké) : rendu 1 km masqué par la densité forêt 1 km ---
    dens = mmap.load_forest_density()
    if dens is not None and dens.shape == grid.shape:
        grid = np.where(dens >= FOREST_MASK_MIN, grid, np.nan).astype(np.float32)
    arr, bounds = _reproject_to_3857(np.ascontiguousarray(_mask_to_france(grid, ref)),
                                     str(ref), resampling=RioResampling.nearest)
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
    return {"url": _bust(f"radar_{key}.png"), "bounds": bounds, "date": date,
            "species": species, "legend": {"species": species}}


# ===== « Radar à champignons » en TUILES (contours forêt exacts à tous les zooms) =====
# Une tuile = valeur (habitat×pousse) 1 km RÉÉCHANTILLONNÉE LISSE (bilinéaire) à la résolution
# du zoom, CLIPPÉE au contour forêt via la tuile BD Forêt WMTS de mêmes z/x/y (pixel-alignée
# → contours exacts, identiques au calque forêt). Rendu mis en cache disque.
_FOREST_TILE_DIR = MASK_CACHE / "foresttiles"     # cache permanent (couche statique)
_RADAR_TILE_DIR = MASK_CACHE / "radartiles"       # cache par jour/sélection
# Contour forêt du radar : tuile BD Forêt WMTS pixel-exacte (bordures NETTES) à partir de
# ce zoom, masque baké 400 m en-dessous. Mis à 0 → contours nets À TOUS LES ZOOMS, servis
# depuis le cache disque pré-rempli (scripts/bake_forest_tiles.py) : zéro réseau en régime
# permanent. Le masque ne sert plus que de repli si une tuile WMTS manque encore au cache.
# (Le zoom natif du radar est plafonné côté carte → on n'a jamais besoin de z > FOREST_MAX_Z.)
FOREST_CRISP_ZOOM = 0
FOREST_MAX_Z = 13                                 # zoom natif max pré-stocké (cf. app.js maxNativeZoom)
_radar_grid_cache: dict = {}
_radar_grid_lock = threading.Lock()






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
        url = ("https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
               "&LAYER=LANDCOVER.FORESTINVENTORY.V2&STYLE=normal&TILEMATRIXSET=PM"
               f"&FORMAT=image/png&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}")
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
    px = (me - mw) / W            # taille pixel masque (m, 3857)
    py = (mn - ms) / H
    tw, ts, te, tn = _tile_bbox_3857(z, x, y)
    # Fenêtre du masque couvrant la tuile (+1 px de marge), bornée à la grille.
    c0 = max(0, int(math.floor((tw - mw) / px)) - 1)
    c1 = min(W, int(math.ceil((te - mw) / px)) + 1)
    r0 = max(0, int(math.floor((mn - tn) / py)) - 1)
    r1 = min(H, int(math.ceil((mn - ts) / py)) + 1)
    if c1 <= c0 or r1 <= r0:
        return np.zeros((256, 256), np.uint8)   # hors emprise (océan/étranger) → pas de forêt
    sub = mask[r0:r1, c0:c1]
    if not sub.any():
        return np.zeros((256, 256), np.uint8)   # dans l'emprise mais aucune forêt
    from rasterio.transform import from_bounds as _fb
    sw, se = mw + c0 * px, mw + c1 * px
    sn, ss = mn - r0 * py, mn - r1 * py
    dst = np.zeros((256, 256), np.float32)
    rio_reproject(source=np.ascontiguousarray(sub, np.float32), destination=dst,
                  src_transform=_fb(sw, ss, se, sn, sub.shape[1], sub.shape[0]),
                  src_crs=RioCRS.from_epsg(3857),
                  dst_transform=_fb(tw, ts, te, tn, 256, 256),
                  dst_crs=RioCRS.from_epsg(3857), resampling=RioResampling.nearest)
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
        if key not in _radar_grid_cache:                 # double-check après acquisition
            if len(_radar_grid_cache) > 8:
                _radar_grid_cache.clear()
            _radar_grid_cache[key] = fruiting_live.radar(species_list, ref_date,
                                                         params=_radar_species_params())
        return _radar_grid_cache[key]


def radar_tile_png(z, x, y, species_list, ref_date=None) -> bytes:
    """PNG 256×256 d'une tuile radar (cache disque). Transparent si rien à montrer."""
    z, x, y = int(z), int(x), int(y)
    if not (0 <= z <= 19 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
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
        return _blank_tile()                              # hors forêt → rien (pas de cache)
    from rasterio.transform import from_bounds as _fb
    west, south, east, north = _tile_bbox_3857(z, x, y)
    src_crs, src_tr = _grid_ref_geo(str(ref))
    val = np.full((256, 256), np.nan, np.float32)
    rio_reproject(source=np.ascontiguousarray(grid, np.float32), destination=val,
                  src_transform=src_tr, src_crs=src_crs,
                  dst_transform=_fb(west, south, east, north, 256, 256),
                  dst_crs=RioCRS.from_epsg(3857), resampling=RioResampling.bilinear,
                  src_nodata=np.nan, dst_nodata=np.nan)
    finite = np.isfinite(val) & (alpha_forest > 10)
    if not bool(finite.any()):
        png = _blank_tile()
    else:
        norm = np.clip(np.nan_to_num(val, nan=0.0) / RADAR_VMAX, 0.0, 1.0).astype(np.float32)
        img = np.zeros((256, 256, 4), np.uint8)
        img[..., :3] = _YLGN_LUT[(norm * 255).astype(np.uint8)]
        img[..., 3] = (np.clip(np.where(finite, 0.15 + 0.8 * norm, 0.0), 0, 1) * 255).astype(np.uint8)
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
    return [noms.get(s, s) for s in species_list
            if s in served and month in mset.get(s, set())]


# ===== Statut « propice » des spots enregistrés =====
# L'indice du radar est calé sur une ÉCHELLE ABSOLUE (RADAR_VMAX), pas sur le P99 du
# jour : en période globalement défavorable la carte reste sombre (et non « la moins
# pire = 100 % »). Un spot est « vraiment propice » quand l'indice dépasse les deux
# seuils ci-dessous. Tous volontairement faciles à ajuster.
FOREST_MASK_MIN = 0.05  # densité forêt (BD Forêt 1 km) mini pour AFFICHER le radar sur la maille


def _radar_species_params():
    """Paramètres mycologiques par espèce (depuis MUSHROOMS) passés au radar pour
    moduler la fenêtre de pousse : délai post-pluie, cumul mini, plage de température."""
    return {m["latin"]: {"rain_lag": tuple(m["rain_lag"]), "rain_min": m["rain_min"],
                         "t_min": m["t_min"], "t_max": m["t_max"],
                         "months": list(m["months"])} for m in MUSHROOMS}


def spots_status(spots, ref_date: str | None = None, selected: list[str] | None = None):
    """Pour une liste de spots [{lat, lon, …}], renvoie le statut courant en
    échantillonnant UNE seule fois la grille radar (habitat × pousse du jour) sur
    la sélection d'espèces du compte. Chaque spot reçoit {score, score_pct, propice,
    date}. Rapide : la grille radar repose sur des couches/scores bakés (cache .npy)."""
    served = set(fruiting_models())
    sel = [s for s in (selected or [m["latin"] for m in MUSHROOMS]) if s in served]
    grid, used, date_iso = fruiting_live.radar(sel, ref_date, params=_radar_species_params())

    out = []
    for sp in spots:
        score = score_pct = None
        if grid is not None:
            row = int(round((fruiting_live.LAT0 - float(sp["lat"])) / fruiting_live.RES))
            col = int(round((float(sp["lon"]) - fruiting_live.LON0) / fruiting_live.RES))
            if 0 <= row < grid.shape[0] and 0 <= col < grid.shape[1]:
                val = grid[row, col]
                if np.isfinite(val):
                    score = float(val)
                    score_pct = int(max(0, min(100, round(100.0 * score / RADAR_VMAX))))
        propice = (score is not None and score >= PROPICE_MIN
                   and score_pct is not None and score_pct >= PROPICE_PCT)
        out.append({**sp, "score": score, "score_pct": score_pct,
                    "propice": propice, "date": date_iso})
    return out


# ===== Overlay « type de sol » (classes texturales SoilGrids) =====
# Palette pédologique : sable=jaune → limon=olive → argile=brun-rouge.
SOIL_COLORS = {
    "sand":            "#efd081", "loamy_sand":      "#e4c172",
    "sandy_loam":      "#d3ad63", "loam":            "#b98f50",
    "silt_loam":       "#aac06a", "silt":            "#c7da8b",
    "sandy_clay_loam": "#c08a54", "clay_loam":       "#a9743f",
    "silty_clay_loam": "#8f9a4f", "sandy_clay":      "#b1623a",
    "silty_clay":      "#8c5a40", "clay":            "#7a4630",
}




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
    idx_f = _mask_to_france(idx_f, ref)   # clippe à la France (pas de pays voisins)
    arr, bounds = _reproject_to_3857(np.ascontiguousarray(idx_f), str(ref),
                                     resampling=RioResampling.nearest)

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
    legend = [{"key": k, "label": soil_data.TEXTURE_FR[k], "color": SOIL_COLORS[k]}
              for k in soil_data.CLASS_ORDER if k in present]
    return {"url": _bust("soil_texture.png"), "bounds": bounds, "legend": legend}


# ===== Analyse météo d'un point + champignons =====
def _latest_soil_point(prefix: str, ref_date_str: str, lat: float, lon: float):
    """Échantillonne le raster sol PREFIX_*.tif (SM/TS) le plus récent ≤ ref_date
    au point (lat, lon). Le sol n'est rafraîchi qu'~1×/jour → tolérance de date."""
    ref = datetime.datetime.strptime(ref_date_str, "%Y%m%d").date()
    best = None
    for f in DATA_DIR.glob(f"{prefix}_*.tif"):
        try:
            d = datetime.datetime.strptime(f.stem.split("_")[-1], "%Y%m%d").date()
        except Exception:
            continue
        if d <= ref and (best is None or d > best[0]):
            best = (d, f)
    return sample_raster(best[1], lon, lat) if best else None


def analyze_point_weather(lat, lon, ref_date_str, available_date_strs, lookback=20):
    """Synthèse météo + état du sol au point. Pluie 7/14 j, jours depuis pluie et T° air
    récente sont tirés de la MÊME grille Open-Meteo que le radar
    (fruiting_live.recent_temporal_grid, en cache) → fiche et radar COHÉRENTS, et
    instantané (aucun appel réseau). Repli sur les rasters RR/T si la grille manque.
    Humidité/T° du sol = rasters SM/TS du jour."""
    ref = datetime.datetime.strptime(ref_date_str, "%Y%m%d").date()

    rain7 = rain14 = days_since_rain = temp_mean = None
    g = None
    try:
        g = fruiting_live.recent_temporal_grid(ref.isoformat())
    except Exception:
        g = None
    if g is not None:
        row = int(round((fruiting_live.LAT0 - lat) / fruiting_live.RES))
        col = int(round((lon - fruiting_live.LON0) / fruiting_live.RES))
        if 0 <= row < fruiting_live.GRID_H and 0 <= col < fruiting_live.GRID_W:
            def _samp(name):
                arr = g.get(name)
                if arr is None:
                    return None
                v = float(arr[row, col])
                return v if np.isfinite(v) else None
            rain7, rain14, temp_mean = _samp("rain7"), _samp("rain14"), _samp("tmean14")
            dsr = _samp("days_since_rain")
            days_since_rain = int(round(dsr)) if dsr is not None else None

    n_days = fruiting_live.WIN
    if rain7 is None and rain14 is None and temp_mean is None:   # repli rasters
        recs = []
        for ds in available_date_strs:
            d = datetime.datetime.strptime(ds, "%Y%m%d").date()
            if 0 <= (ref - d).days <= lookback:
                recs.append((d, sample_raster(DATA_DIR / f"RR_{ds}.tif", lon, lat),
                             sample_raster(DATA_DIR / f"T_{ds}.tif", lon, lat)))
        rain7 = sum(rr for d, rr, t in recs if rr is not None and (ref - d).days <= 7)
        rain14 = sum(rr for d, rr, t in recs if rr is not None and (ref - d).days <= 14)
        for d, rr, t in sorted(recs, key=lambda r: r[0], reverse=True):
            if rr is not None and rr >= 8.0:
                days_since_rain = (ref - d).days
                break
        temps = [t for d, rr, t in recs if t is not None and (ref - d).days <= 7]
        temp_mean = float(np.mean(temps)) if temps else None
        n_days = len(recs)

    soil_moisture = _latest_soil_point("SM", ref_date_str, lat, lon)
    soil_temp = _latest_soil_point("TS", ref_date_str, lat, lon)
    return {"month": ref.month, "rain7": rain7, "rain14": rain14,
            "days_since_rain": days_since_rain, "temp_mean": temp_mean,
            "soil_moisture": soil_moisture, "soil_temp": soil_temp, "n_days": n_days}


def point_report(lat: float, lon: float, ref_date: str, selected: list[str] | None = None):
    """Rapport complet d'un point : commune, météo, sol (texture/pH/humidité/T°),
    relief (altitude/exposition), essence forestière et classement des champignons.
    `selected` = noms latins choisis par l'utilisateur → marque chaque espèce."""
    dates = [d.strftime("%Y%m%d") for d in available_dates()]
    comm = find_commune_at(lat, lon)
    comm_name = str(comm.get("nom_com", "")) if comm is not None else ""
    rr = sample_raster(DATA_DIR / f"RR_{ref_date}.tif", lon, lat)
    t = sample_raster(DATA_DIR / f"T_{ref_date}.tif", lon, lat)
    w = analyze_point_weather(lat, lon, ref_date, dates)

    # Sol : couches SoilGrids bakées (rapide, hors-ligne, couvre toutes les terres).
    # Pas de repli REST dans le chemin requête (lent + rate-limité) ; un sol absent
    # (mer/urbain sans donnée) s'affiche simplement comme « non disponible ».
    soil = soil_data.sample_soil_static(lat, lon)
    # Relief : grille altitude/exposition bakée (instantané, hors-ligne). On évite
    # l'appel IGN RGE ALTI par point (146–2400 ms !) sur le chemin critique du clic ;
    # le baké (même source IGN, maille ~1 km) suffit largement pour la fiche.
    terrain = terrain_data.sample_terrain_static(lat, lon)

    # Famille d'hôte : lue dans les rasters bakés (instantané, aucun appel réseau).
    # Le libellé d'essence précis (tfv) est fourni à la demande par /api/forest (WMS).
    forest = mmap.family_at_point(round(lat, 4), round(lon, 4))
    family = forest.get("family") if forest else None
    sel = set(selected) if selected else None

    # On ne liste que les espèces réellement modélisées/servies (cf. fruiting_models) :
    # une espèce sans modèle affiché (p.ex. la morille) n'apparaît pas dans la fiche.
    served = set(fruiting_models())

    params_all = _radar_species_params()
    ref_iso = datetime.datetime.strptime(ref_date, "%Y%m%d").date().isoformat()
    items = []
    for m in MUSHROOMS:
        if m["latin"] not in served:
            continue
        in_season = w["month"] in m["months"]
        hm = mmap.host_match(m.get("latin", ""), family)
        phm = _ph_match(soil.get("ph") if soil else None, m.get("ph_opt", (4.0, 8.5)))
        score_pct = None
        if not in_season:
            label, level = ("Hors saison", "off")
        else:
            # Verdict = valeur radar (habitat × pousse) au point, identique à la carte/aux spots.
            score, _d = fruiting_live.blended_at_point(m["latin"], lat, lon, ref_iso,
                                                       params_all.get(m["latin"]))
            if score is not None:
                score_pct = int(max(0, min(100, round(100.0 * score / RADAR_VMAX))))
                label, level = _radar_label(score, score_pct, True)
            else:
                # Repli (pré-score du jour non baké, p.ex. en dev) : ancienne logique météo.
                label, level, _prio, _phm = mushroom_suitability(m, w, soil, terrain)
        items.append({
            "nom": m["nom"], "latin": m["latin"], "color": m["color"],
            "months": sorted(m["months"]), "t_min": m["t_min"], "t_max": m["t_max"],
            "rain_lag": list(m["rain_lag"]), "habitat": m["habitat"],
            "ph_opt": list(m["ph_opt"]), "soil_pref": m.get("soil_pref", ""),
            "label": label, "level": level, "score_pct": score_pct,
            "host": hm, "soil_ph": phm,
            "selected": (sel is None) or (m["latin"] in sel),
            "_rank": (0 if in_season else 1, -(score_pct if score_pct is not None else -1)),
        })
    items.sort(key=lambda e: (e["_rank"], e["nom"]))
    for it in items:
        it.pop("_rank", None)

    return {
        "lat": lat, "lon": lon, "commune": comm_name, "month": MONTHS_FR[w["month"] - 1],
        "rr": rr, "t": t, "rain7": w["rain7"], "rain14": w["rain14"],
        "days_since_rain": w["days_since_rain"], "temp_mean": w["temp_mean"],
        "soil_moisture": w["soil_moisture"], "soil_temp": w["soil_temp"],
        "n_days": w["n_days"], "soil": soil, "terrain": terrain,
        "forest": forest, "family": family, "mushrooms": items,
    }
