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

# Champignons comestibles de France. Champs :
#   months, t_min/t_max (T° air propice), rain_lag/rain_min (délai & cumul post-pluie),
#   habitat ; ph_opt = plage de pH du sol favorable (calcicole vs acidophile),
#   soil_pref = libellé sol affiché. Le pH est documenté en mycologie (les bolets/
#   girolles/chanterelles sont acidophiles ; morilles & mousseron calcicoles ; le
#   pleurote, saprophyte du bois mort, est indifférent au pH du sol).
MUSHROOMS = [
    {"nom": "Morille", "latin": "Morchella esculenta", "color": "#a16207",
     "months": {3, 4, 5}, "t_min": 8, "t_max": 16, "rain_lag": (5, 16), "rain_min": 15,
     "ph_opt": (6.5, 8.0), "soil_pref": "Calcicole (sols calcaires/neutres)",
     "habitat": "Frênes, ormes, vergers, sols calcaires, anciennes coupes/brûlures"},
    {"nom": "Mousseron de la St-Georges", "latin": "Calocybe gambosa", "color": "#ca8a04",
     "months": {4, 5}, "t_min": 10, "t_max": 17, "rain_lag": (4, 12), "rain_min": 12,
     "ph_opt": (6.3, 7.8), "soil_pref": "Sols neutres à calcaires",
     "habitat": "Prés, lisières, ronds de sorcière (« mousseron de printemps »)"},
    {"nom": "Cèpe d'été / bronzé", "latin": "Boletus aereus", "color": "#92400e",
     "months": {6, 7, 8, 9}, "t_min": 16, "t_max": 25, "rain_lag": (6, 13), "rain_min": 20,
     "ph_opt": (5.0, 7.0), "soil_pref": "Sols acides à neutres", "alt_opt": (0, 900),
     "habitat": "Chênes, châtaigniers, zones chaudes ensoleillées (plaine/colline)"},
    {"nom": "Girolle / Chanterelle", "latin": "Cantharellus cibarius", "color": "#eab308",
     "months": {6, 7, 8, 9, 10}, "t_min": 14, "t_max": 23, "rain_lag": (2, 8), "rain_min": 10,
     "ph_opt": (4.3, 6.0), "soil_pref": "Acidophile (sols acides, moussus)",
     "habitat": "Feuillus & conifères, mousses, talus"},
    {"nom": "Cèpe de Bordeaux", "latin": "Boletus edulis", "color": "#854d0e",
     "months": {8, 9, 10, 11}, "t_min": 12, "t_max": 20, "rain_lag": (7, 16), "rain_min": 20,
     "ph_opt": (4.5, 6.5), "soil_pref": "Sols acides à neutres",
     "habitat": "Chênes, hêtres, châtaigniers, épicéas"},
    {"nom": "Coulemelle (lépiote élevée)", "latin": "Macrolepiota procera", "color": "#a8a29e",
     "months": {7, 8, 9, 10, 11}, "t_min": 12, "t_max": 20, "rain_lag": (4, 11), "rain_min": 12,
     "ph_opt": (5.5, 7.5), "soil_pref": "Sols neutres, riches",
     "habitat": "Prés, lisières, clairières, bords de chemins"},
    {"nom": "Rosé des prés", "latin": "Agaricus campestris", "color": "#fb7185",
     "months": {8, 9, 10}, "t_min": 12, "t_max": 20, "rain_lag": (3, 9), "rain_min": 12,
     "ph_opt": (6.0, 7.5), "soil_pref": "Sols neutres riches (prairies)",
     "habitat": "Prairies pâturées, pelouses (non traitées)"},
    {"nom": "Trompette de la mort", "latin": "Craterellus cornucopioides", "color": "#334155",
     "months": {9, 10, 11}, "t_min": 8, "t_max": 17, "rain_lag": (5, 13), "rain_min": 12,
     "ph_opt": (5.0, 7.2), "soil_pref": "Sols acides à calcaires, humides",
     "habitat": "Feuillus (hêtres, charmes), sols humides moussus"},
    {"nom": "Chanterelle en tube", "latin": "Craterellus tubaeformis", "color": "#d97706",
     "months": {9, 10, 11, 12}, "t_min": 5, "t_max": 15, "rain_lag": (5, 13), "rain_min": 10,
     "ph_opt": (4.0, 5.5), "soil_pref": "Acidophile (conifères, mousses)",
     "habitat": "Conifères, mousses, sols acides"},
    {"nom": "Pied de mouton", "latin": "Hydnum repandum", "color": "#d6d3d1",
     "months": {9, 10, 11, 12}, "t_min": 6, "t_max": 15, "rain_lag": (5, 13), "rain_min": 12,
     "ph_opt": (4.5, 6.5), "soil_pref": "Sols acides à neutres",
     "habitat": "Feuillus & conifères, après écart de température sol/air"},
    {"nom": "Lactaire délicieux", "latin": "Lactarius deliciosus", "color": "#ea580c",
     "months": {9, 10, 11}, "t_min": 8, "t_max": 16, "rain_lag": (5, 12), "rain_min": 12,
     "ph_opt": (5.5, 7.5), "soil_pref": "Sols neutres à calcaires (pins)",
     "habitat": "Pins et conifères"},
    {"nom": "Bolet bai", "latin": "Imleria badia", "color": "#78350f",
     "months": {8, 9, 10, 11}, "t_min": 8, "t_max": 18, "rain_lag": (6, 13), "rain_min": 15,
     "ph_opt": (4.0, 5.8), "soil_pref": "Acidophile (conifères)",
     "habitat": "Conifères surtout, parfois feuillus"},
    {"nom": "Pied bleu", "latin": "Lepista nuda", "color": "#7c3aed",
     "months": {10, 11, 12}, "t_min": 4, "t_max": 13, "rain_lag": (5, 15), "rain_min": 12,
     "ph_opt": (5.5, 7.5), "soil_pref": "Sols neutres, litière riche",
     "habitat": "Feuillus, tas de feuilles, composts ; résiste au frais"},
    {"nom": "Pleurote en huître", "latin": "Pleurotus ostreatus", "color": "#64748b",
     "months": {11, 12, 1, 2}, "t_min": 2, "t_max": 12, "rain_lag": (3, 12), "rain_min": 8,
     "ph_opt": (4.0, 8.5), "soil_pref": "Sur bois mort (sol indifférent)",
     "habitat": "Bois mort (peupliers, hêtres), pousse après refroidissement"},
]


# ===== Données statiques (chargées une fois) =====
@lru_cache(maxsize=1)
def _static():
    villes = pd.read_csv(VILLES_CSV, sep=";")
    for c in ["nom1", "nom2", "nom3", "nom4", "code_postal"]:
        if c not in villes.columns:
            villes[c] = ""
    villes["all_names"] = (
        villes[["nom1", "nom2", "nom3", "nom4", "code_postal"]]
        .astype(str).agg(" ".join, axis=1).str.lower()
    )
    comm = gpd.read_file(COMMUNES_GPKG)
    if comm.crs and comm.crs.to_epsg() != 4326:
        comm = comm.to_crs("EPSG:4326")
    comm = comm.dropna(subset=["geometry"])
    france_boundary = comm.geometry.union_all()

    outline_gdf = None
    try:
        comm_proj = comm.to_crs("EPSG:2154")
        centroids = gpd.GeoSeries(comm_proj.geometry.centroid, crs="EPSG:2154").to_crs("EPSG:4326")
        mask_c = centroids.x.between(-10.0, 12.0) & centroids.y.between(41.0, 52.0)
        mainland = comm[mask_c].copy()
        rep = mainland.geometry.representative_point()
        mainland["sample_lon"] = rep.x
        mainland["sample_lat"] = rep.y
        name_col = next((c for c in ["DCOE_L_LIB", "nom", "name", "NOM_COM", "NOM_COMM", "NOM", "libelle"]
                         if c in mainland.columns), None)
        if name_col:
            mainland = mainland.rename(columns={name_col: "nom_com"})
        cols = ["geometry", "sample_lon", "sample_lat"] + (["nom_com"] if "nom_com" in mainland.columns else [])
        outline_gdf = mainland[cols].copy()
        outline_gdf.geometry = outline_gdf.geometry.simplify(0.01, preserve_topology=False)
        outline_gdf = outline_gdf.rename(columns={"sample_lon": "lon", "sample_lat": "lat"})
    except Exception:
        outline_gdf = None
    return villes, comm, france_boundary, outline_gdf


def search_cities(query: str, limit: int = 12):
    villes, *_ = _static()
    q = (query or "").strip().lower()
    if not q:
        return []
    m = villes[villes["all_names"].str.contains(q, na=False)].head(limit)
    out = []
    for _, r in m.iterrows():
        out.append({"label": f"{r['nom1']} ({r['code_postal']})",
                    "name": str(r["nom1"]), "lat": float(r["latitude"]), "lon": float(r["longitude"])})
    return out


def find_commune_at(lat: float, lon: float):
    _, _, _, outline_gdf = _static()
    if outline_gdf is None or outline_gdf.empty:
        return None
    try:
        pt = Point(lon, lat)
        idx = list(outline_gdf.sindex.query(pt, predicate="intersects"))
        if idx:
            return outline_gdf.iloc[idx[0]]
        dists = outline_gdf.geometry.distance(pt)
        nearest = dists.idxmin()
        if dists[nearest] < 0.05:
            return outline_gdf.loc[nearest]
    except Exception:
        pass
    return None


@lru_cache(maxsize=1)
def france_outline_geojson():
    _, _, france_boundary, _ = _static()
    if france_boundary is None:
        return None
    try:
        return mapping(france_boundary.simplify(0.01, preserve_topology=True))
    except Exception:
        return None


# ===== Dates / rasters =====
def available_dates():
    out = []
    for f in DATA_DIR.glob("RR_*.tif"):
        try:
            out.append(datetime.datetime.strptime(f.stem.replace("RR_", "").split("_")[0], "%Y%m%d").date())
        except Exception:
            pass
    return sorted(set(out))


def sample_raster(raster_path, lon, lat):
    try:
        with rasterio.open(raster_path) as src:
            raw = list(src.sample([(lon, lat)]))[0][0]
            if src.nodata is not None and raw == src.nodata:
                return None
            return float(raw) if raw is not None and not np.isnan(raw) else None
    except Exception:
        return None


def _france_mask(raster_path: str):
    cache_file = MASK_CACHE / f"france_mask_{Path(raster_path).stem}.npy"
    if cache_file.exists():
        try:
            m = np.load(cache_file)
            if m.dtype == bool:
                return m
        except Exception:
            pass
    _, _, france_boundary, _ = _static()
    with rasterio.open(raster_path) as src:
        out_shape = (src.height, src.width)
        transform = src.transform
    mask_bool = features.rasterize([(france_boundary, 1)], out_shape=out_shape, transform=transform,
                                   fill=0, default_value=1, dtype="uint8").astype(bool)
    try:
        np.save(cache_file, mask_bool)
    except Exception:
        pass
    return mask_bool


def _aggregate(dates, var):
    arrs = []
    for d in dates:
        f = DATA_DIR / (f"RR_{d}.tif" if var == "RR" else f"T_{d}.tif")
        if not f.exists():
            continue
        with rasterio.open(f) as src:
            a = src.read(1).astype(np.float32)
            if src.nodata is not None:
                a[a == src.nodata] = np.nan
            arrs.append(np.ma.masked_invalid(a))
    if not arrs:
        return None
    stacked = np.ma.stack(arrs)
    return stacked.sum(axis=0) if var == "RR" else stacked.mean(axis=0)


def _reproject_to_3857(arr_src, raster_path, resampling=RioResampling.bilinear):
    """Reprojette un tableau (grille du raster) en EPSG:3857 ; renvoie (arr, bounds_latlon).
    resampling=nearest pour les champs catégoriels (ex. classes de sol)."""
    with rasterio.open(raster_path) as src:
        src_crs = src.crs or RioCRS.from_epsg(4326)
        src_transform, src_w, src_h, src_bounds = src.transform, src.width, src.height, src.bounds
    left, bottom, right, top = src_bounds
    wm = RioCRS.from_epsg(3857)
    dtr, dw, dh = calculate_default_transform(src_crs, wm, src_w, src_h, *src_bounds)
    dst = np.full((dh, dw), np.nan, dtype=np.float32)
    rio_reproject(source=arr_src, destination=dst, src_transform=src_transform, src_crs=src_crs,
                  dst_transform=dtr, dst_crs=wm, resampling=resampling,
                  src_nodata=np.nan, dst_nodata=np.nan)
    el, et = dtr.c, dtr.f
    er, eb = el + dw * dtr.a, et + dh * dtr.e
    left, bottom, right, top = rio_transform_bounds(wm, RioCRS.from_epsg(4326), el, eb, er, et)
    return dst, {"left": float(left), "bottom": float(bottom), "right": float(right), "top": float(top)}


def _save_png(rgba_uint8, fname, resample=None):
    from PIL import Image
    if resample is None:
        resample = Image.LANCZOS
    im = Image.fromarray(rgba_uint8, mode="RGBA")
    w, h = im.size
    if max(w, h) > 2048:
        s = 2048 / max(w, h)
        im = im.resize((max(1, int(w * s)), max(1, int(h * s))), resample)
    im.save(OVERLAY_DIR / fname, format="PNG", optimize=True, compress_level=6)
    return f"/overlays/{fname}"


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


def _bust(fname: str) -> str:
    """URL d'overlay avec cache-busting (?v=mtime) pour les noms de fichiers
    stables (sol/humidité/altitude/exposition) — évite un PNG périmé en cache."""
    import os
    try:
        return f"/overlays/{fname}?v={int(os.path.getmtime(OVERLAY_DIR / fname))}"
    except Exception:
        return f"/overlays/{fname}"


def _grid_ref():
    """Raster de référence (géoréférencement de la grille) : n'importe quel RR/T."""
    dts = available_dates()
    if dts:
        cand = DATA_DIR / f"RR_{dts[-1].strftime('%Y%m%d')}.tif"
        if cand.exists():
            return cand
    tifs = sorted(DATA_DIR.glob("RR_*.tif")) or sorted(DATA_DIR.glob("T_*.tif"))
    return tifs[-1] if tifs else None


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


def _mask_to_france(grid2d, ref):
    """Met à NaN les cellules hors frontière France → l'overlay épouse les contours
    (et n'apparaît pas en rectangle sur la mer / les pays voisins)."""
    g = np.asarray(grid2d, np.float32).copy()
    try:
        mask = _france_mask(str(ref))
        if mask.shape == g.shape:
            g[~mask] = np.nan
    except Exception:
        pass
    return g


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
    arr, bounds = _reproject_to_3857(np.ascontiguousarray(_mask_to_france(grid, ref)), str(ref))
    finite = np.isfinite(arr)
    if not finite.any():
        return None
    # Échelle ABSOLUE (RADAR_VMAX) et non P99 du jour : hors-saison reste sombre au lieu
    # d'afficher faussement « la moins pire = vert foncé ». Cohérent avec spots_status.
    norm = np.clip(np.where(finite, arr, 0.0) / RADAR_VMAX, 0.0, 1.0)
    rgba = plt.cm.YlGn(norm)
    img = np.zeros((arr.shape[0], arr.shape[1], 4), np.uint8)
    img[..., :3] = (rgba[..., :3] * 255).astype(np.uint8)
    alpha = np.where(finite, 0.15 + 0.8 * norm, 0.0)      # transparent où faible, marqué où chaud
    img[..., 3] = (np.clip(alpha, 0, 1) * 255).astype(np.uint8)
    key = hashlib.md5(("radar" + str(date) + ",".join(sorted(used))).encode()).hexdigest()[:12]
    _save_png(img, f"radar_{key}.png")
    noms = {m["latin"]: m["nom"] for m in MUSHROOMS}
    return {"url": _bust(f"radar_{key}.png"), "bounds": bounds, "date": date,
            "species": [noms.get(s, s) for s in used],
            "legend": {"species": [noms.get(s, s) for s in used]}}


# ===== Statut « propice » des spots enregistrés =====
# L'indice du radar est calé sur une ÉCHELLE ABSOLUE (RADAR_VMAX), pas sur le P99 du
# jour : en période globalement défavorable la carte reste sombre (et non « la moins
# pire = 100 % »). Un spot est « vraiment propice » quand l'indice dépasse les deux
# seuils ci-dessous. Tous volontairement faciles à ajuster.
RADAR_VMAX = 0.60    # valeur radar brute (habitat×moment) correspondant à l'indice 100 %
PROPICE_MIN = 0.30   # garde-fou absolu sur la valeur radar brute
PROPICE_PCT = 70     # % de l'indice (vs RADAR_VMAX) requis pour « propice »


def _radar_species_params():
    """Paramètres mycologiques par espèce (depuis MUSHROOMS) passés au radar pour
    moduler la fenêtre de pousse : délai post-pluie, cumul mini, plage de température."""
    return {m["latin"]: {"rain_lag": tuple(m["rain_lag"]), "rain_min": m["rain_min"],
                         "t_min": m["t_min"], "t_max": m["t_max"]} for m in MUSHROOMS}


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


def _hex_to_rgb(h: str):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


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


def _ph_match(ph, ph_opt) -> str:
    """'ok' (pH dans la plage), 'mid' (proche), 'no' (inadapté) ou 'unknown'."""
    if ph is None:
        return "unknown"
    lo, hi = ph_opt
    if (lo - 0.3) <= ph <= (hi + 0.3):
        return "ok"
    if (lo - 1.0) <= ph <= (hi + 1.0):
        return "mid"
    return "no"


def _altitude_fit_point(alt, alt_opt):
    """Adéquation altitude scalaire (0.3..1) — même logique que la carte :
    pénalité au-dessus de ~1800 m (limite forestière) + fenêtre par espèce."""
    if alt is None:
        return 1.0
    treeline = 1.0 - min(max((alt - 1800.0) / 600.0, 0.0), 0.6)
    if alt_opt:
        lo, hi = alt_opt
        below = min(max((lo - alt) / 400.0, 0.0), 1.0)
        above = min(max((alt - hi) / 400.0, 0.0), 1.0)
        window = 0.4 + 0.6 * max(0.0, 1.0 - below - above)
    else:
        window = 1.0
    return max(0.3, min(1.0, treeline * window))


def _aspect_fit_point(northness, month):
    """Modulateur exposition scalaire (0.85..1.15) — même logique saisonnière que
    la carte (été → versant nord/frais, automne-hiver → versant sud/chaud)."""
    if northness is None:
        return 1.0
    w = mmap._ASPECT_W.get(month, 0.0)
    return float(np.clip(1.0 + w * northness, 0.85, 1.15))


def mushroom_suitability(m, w, soil=None, terrain=None):
    """Classe l'adéquation d'une espèce au point : saison, T° (air+sol), humidité
    (pluie récente OU sol humide), pH, ALTITUDE et EXPOSITION — cohérent avec le
    modèle de la carte. Renvoie (label, niveau, priorité_tri, ph_match)."""
    if w["month"] not in m["months"]:
        return ("Hors saison", "off", 3, "unknown")

    ta, ts = w.get("temp_mean"), w.get("soil_temp")
    if ta is not None and ts is not None:
        temp = 0.5 * ta + 0.5 * ts
    else:
        temp = ta if ta is not None else ts
    temp_ok = temp is not None and (m["t_min"] - 1) <= temp <= (m["t_max"] + 1)

    lag_lo, lag_hi = m["rain_lag"]
    dsr = w["days_since_rain"]
    rain_ok = dsr is not None and lag_lo <= dsr <= lag_hi and (w.get("rain14") or 0) >= m["rain_min"]
    sm = w.get("soil_moisture")
    moist_ok = rain_ok or (sm is not None and sm >= 0.22)

    ph = soil.get("ph") if soil else None
    phm = _ph_match(ph, m.get("ph_opt", (4.0, 8.5)))
    ph_bad = phm == "no"

    # Relief : altitude (par espèce + limite forestière) et exposition (saisonnière)
    alt = terrain.get("altitude") if terrain else None
    north = terrain.get("northness") if terrain else None
    alt_fit = _altitude_fit_point(alt, m.get("alt_opt"))
    asp_fit = _aspect_fit_point(north, w["month"])
    alt_bad = alt_fit < 0.6
    # tri : meilleure altitude/exposition → priorité plus basse (remonte la liste)
    terr_adj = (1.0 - alt_fit * asp_fit) * 0.6

    if temp_ok and moist_ok and not ph_bad and not alt_bad:
        return ("Favorable", "good", 0.0 + terr_adj, phm)
    if alt_bad and (temp_ok or moist_ok):
        return ("Altitude peu adaptée", "mid", 1.5 + terr_adj, phm)
    if ph_bad and (temp_ok or moist_ok):
        return ("Sol peu adapté", "mid", 1.5 + terr_adj, phm)
    if temp_ok or moist_ok:
        return ("Conditions partielles", "mid", 1.0 + terr_adj, phm)
    return ("Peu probable", "bad", 2.0 + terr_adj, phm)


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

    items = []
    for m in MUSHROOMS:
        if m["latin"] not in served:
            continue
        label, level, prio, phm = mushroom_suitability(m, w, soil, terrain)
        hm = mmap.host_match(m.get("latin", ""), family)
        host_adj = {"ok": -0.5, "no": 1.5, "unknown": 0.0}[hm]
        items.append({
            "nom": m["nom"], "latin": m["latin"], "color": m["color"],
            "months": sorted(m["months"]), "t_min": m["t_min"], "t_max": m["t_max"],
            "rain_lag": list(m["rain_lag"]), "habitat": m["habitat"],
            "ph_opt": list(m["ph_opt"]), "soil_pref": m.get("soil_pref", ""),
            "label": label, "level": level, "host": hm, "soil_ph": phm,
            "selected": (sel is None) or (m["latin"] in sel),
            "_score": prio + host_adj,
        })
    items.sort(key=lambda e: (e["_score"], e["nom"]))
    for it in items:
        it.pop("_score", None)

    return {
        "lat": lat, "lon": lon, "commune": comm_name, "month": MONTHS_FR[w["month"] - 1],
        "rr": rr, "t": t, "rain7": w["rain7"], "rain14": w["rain14"],
        "days_since_rain": w["days_since_rain"], "temp_mean": w["temp_mean"],
        "soil_moisture": w["soil_moisture"], "soil_temp": w["soil_temp"],
        "n_days": w["n_days"], "soil": soil, "terrain": terrain,
        "forest": forest, "family": family, "mushrooms": items,
    }
