#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Relief : altitude + exposition (versant nord/sud) — Python pur, sans clé API.

Deux briques (comme soil_data.py / mushroom_map.py) :

1. NATIONAL (le « où ») — altitude bakée une fois sur la grille météo (1601×1051,
   EPSG:4326) via l'IGN RGE ALTI (REST, bulk 200 pts/req), puis pente &
   « northness » (cos de l'azimut du versant ∈ [-1=sud, +1=nord]) dérivés par
   gradient. Caches : data/cache/altitude.npy / terrain_northness.npy /
   terrain_slope.npy. Servent au modèle de favorabilité + aux calques.
   (Open-Meteo Elevation a été écarté : son quota se compte PAR POINT → une grille
   nationale dépasse la limite horaire gratuite.)

2. AU POINT (le « quoi ») — terrain_at_point() interroge l'IGN RGE ALTI (REST,
   ~1-25 m) au point + 4 voisins → altitude précise, pente %, exposition locale
   (versant N/S/E/O). Repli sur la grille bakée si l'IGN est injoignable.

Grille alignée sur les rasters météo RR_*.tif / T_*.tif (interpret_day).
"""
from __future__ import annotations
import time
import urllib.parse
import urllib.request
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

# Grille de référence (centres) — identique à interpret_day / soil_data.
GRID_W, GRID_H = 1601, 1051
GRID_RES = 0.01
GRID_LON0, GRID_LAT0 = -5.5, 51.5   # centre coin haut-gauche (lon min, lat max)

CACHE_DIR = Path("data/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
_ALT_NPY = CACHE_DIR / "altitude.npy"
_NORTH_NPY = CACHE_DIR / "terrain_northness.npy"
_SLOPE_NPY = CACHE_DIR / "terrain_slope.npy"

IGN_ALTI_URL = "https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json"
_IGN_MAX = 200  # points max par requête REST IGN

# Grille d'échantillonnage altitude : ~0.1° (relief national lissé ; le point
# utilise l'IGN RGE ALTI précis, donc une grille grossière suffit pour le bake).
OM_RES = 0.1
OM_EXTENT = (-5.5, 10.5, 41.0, 51.5)  # lon_min, lon_max, lat_min, lat_max

_DEG_M = 111320.0  # mètres par degré de latitude


# --------------------------------------------------------------------------- #
#  1. Bake national (IGN RGE ALTI → altitude → pente/northness)
# --------------------------------------------------------------------------- #
def _om_grid_points():
    lo0, lo1, la0, la1 = OM_EXTENT
    lons = np.arange(lo0, lo1 + OM_RES / 2, OM_RES)
    lats = np.arange(la0, la1 + OM_RES / 2, OM_RES)
    lonv, latv = np.meshgrid(lons, lats)
    return np.column_stack([lonv.ravel(), latv.ravel()])


def _slope_northness(alt: np.ndarray):
    """Calcule pente (%) et northness (-1 sud … +1 nord) depuis l'altitude (m)
    sur la grille 0.01°. Lignes = latitude décroissante (haut=nord)."""
    # mètres par pas de grille
    lats = GRID_LAT0 - np.arange(GRID_H) * GRID_RES          # latitude de chaque ligne
    d_north = GRID_RES * _DEG_M                               # m / ligne (constant)
    d_east = GRID_RES * _DEG_M * np.cos(np.radians(lats))     # m / colonne (par ligne)
    d_east = np.clip(d_east, 1.0, None)[:, None]             # (H,1) broadcast

    z = np.where(np.isnan(alt), np.nanmean(alt[np.isfinite(alt)]) if np.isfinite(alt).any() else 0.0, alt)
    gx = np.gradient(z, axis=1) / d_east                      # dZ/d(est)  (m/m)
    gy = -np.gradient(z, axis=0) / d_north                    # dZ/d(nord) (m/m)
    grad = np.sqrt(gx ** 2 + gy ** 2)
    slope_pct = (grad * 100.0).astype(np.float32)
    with np.errstate(invalid="ignore", divide="ignore"):
        northness = np.where(grad > 1e-6, -gy / grad, 0.0).astype(np.float32)
    return slope_pct, northness


def build_terrain_static(force: bool = False) -> dict | None:
    """Bake l'altitude (Open-Meteo) sur la grille + pente/northness. Renvoie
    {'altitude','northness','slope'} ou None si Open-Meteo injoignable."""
    if not force and _ALT_NPY.exists() and _NORTH_NPY.exists() and _SLOPE_NPY.exists():
        got = load_terrain_static()
        if got is not None:
            return got
    from interpret_day import build_grid, idw

    pts = _om_grid_points()
    elevs = []
    for i in range(0, len(pts), _IGN_MAX):
        chunk = [(float(p[0]), float(p[1])) for p in pts[i:i + _IGN_MAX]]
        el = _ign_elevations(chunk)
        if el is None:                       # 1 retry
            time.sleep(1.0)
            el = _ign_elevations(chunk)
        elevs.extend(el if el is not None else [np.nan] * len(chunk))
        time.sleep(0.15)
    elevs = np.asarray(elevs, dtype=np.float64)
    elevs[elevs < -1000.0] = np.nan          # sentinel mer/hors-couverture IGN → NaN
    if not np.isfinite(elevs).any():
        return None

    lonv, latv, grid_pts = build_grid()
    keep = np.isfinite(elevs)
    alt = idw(pts[keep], elevs[keep], grid_pts, power=2, k=8).reshape(lonv.shape).astype(np.float32)
    slope, northness = _slope_northness(alt)

    try:
        np.save(_ALT_NPY, alt)
        np.save(_SLOPE_NPY, slope)
        np.save(_NORTH_NPY, northness)
    except Exception:
        pass
    return {"altitude": alt, "slope": slope, "northness": northness}


_TERRAIN_CACHE: dict | None = None


def load_terrain_static() -> dict | None:
    """Charge altitude/pente/northness bakés (.npy) — LECTURE SEULE (ne bake
    jamais dans le chemin requête ; le bake long est fait par le scheduler/CLI).
    Renvoie {'altitude','slope','northness'} ou None ; ne cache qu'un succès."""
    global _TERRAIN_CACHE
    if _TERRAIN_CACHE is not None:
        return _TERRAIN_CACHE
    if _ALT_NPY.exists() and _NORTH_NPY.exists() and _SLOPE_NPY.exists():
        try:
            alt, slope, north = np.load(_ALT_NPY), np.load(_SLOPE_NPY), np.load(_NORTH_NPY)
            if alt.shape == (GRID_H, GRID_W):
                _TERRAIN_CACHE = {"altitude": alt, "slope": slope, "northness": north}
                return _TERRAIN_CACHE
        except Exception:
            pass
    return None


# --------------------------------------------------------------------------- #
#  2. Exposition / altitude au point (IGN RGE ALTI, précis)
# --------------------------------------------------------------------------- #
def _exposition_label(slope_pct: float, azimuth_deg: float | None) -> str:
    """Libellé d'exposition à partir de la pente et de l'azimut du versant
    (azimut = direction de la descente, 0=N, 90=E, 180=S, 270=O)."""
    if slope_pct is None or slope_pct < 3.0 or azimuth_deg is None:
        return "Terrain plat / replat"
    dirs = ["nord", "nord-est", "est", "sud-est", "sud", "sud-ouest", "ouest", "nord-ouest"]
    idx = int(((azimuth_deg % 360) + 22.5) // 45) % 8
    return f"Versant {dirs[idx]}"


def _ign_elevations(coords_lonlat) -> list[float] | None:
    lons = "|".join(f"{c[0]:.6f}" for c in coords_lonlat)
    lats = "|".join(f"{c[1]:.6f}" for c in coords_lonlat)
    params = {"lon": lons, "lat": lats, "resource": "ign_rge_alti_wld", "zonly": "true"}
    url = IGN_ALTI_URL + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            j = json.loads(r.read().decode("utf-8", "ignore"))
        el = j.get("elevations")
        if isinstance(el, list) and len(el) == len(coords_lonlat):
            return [float(x) for x in el]
    except Exception:
        pass
    return None


@lru_cache(maxsize=4096)
def terrain_at_point(lat: float, lon: float) -> dict | None:
    """Altitude précise + pente + exposition au point via IGN RGE ALTI (centre +
    4 voisins ±~120 m). Repli sur la grille bakée. Renvoie
    {altitude, slope_pct, exposition, northness, source} ou None."""
    d_m = 120.0
    dlat = d_m / _DEG_M
    dlon = d_m / (_DEG_M * max(0.2, np.cos(np.radians(lat))))
    # ordre : C, N, S, E, O  (lon, lat)
    coords = [(lon, lat), (lon, lat + dlat), (lon, lat - dlat),
              (lon + dlon, lat), (lon - dlon, lat)]
    el = _ign_elevations(coords)
    if el is not None and all(np.isfinite(el)) and any(v > -1000 for v in el):
        c, n, s, e, w = el
        gx = (e - w) / (2 * d_m)          # dZ/d(est)
        gy = (n - s) / (2 * d_m)          # dZ/d(nord)
        grad = float(np.hypot(gx, gy))
        slope_pct = round(grad * 100.0, 1)
        if grad > 1e-6:
            # azimut de la descente (versant) : direction de -(gx,gy)
            azimuth = (np.degrees(np.arctan2(-gx, -gy))) % 360.0
            northness = round(-gy / grad, 2)
        else:
            azimuth, northness = None, 0.0
        return {"altitude": round(c, 1), "slope_pct": slope_pct,
                "exposition": _exposition_label(slope_pct, azimuth),
                "northness": northness, "source": "IGN RGE ALTI"}
    return sample_terrain_static(lat, lon)


def sample_terrain_static(lat: float, lon: float) -> dict | None:
    """Repli hors-ligne : altitude/pente/exposition depuis la grille bakée."""
    g = load_terrain_static()
    if g is None:
        return None
    col = int(round((lon - GRID_LON0) / GRID_RES))
    row = int(round((GRID_LAT0 - lat) / GRID_RES))
    if not (0 <= row < GRID_H and 0 <= col < GRID_W):
        return None
    alt = g["altitude"][row, col]
    slope = float(g["slope"][row, col])
    north = float(g["northness"][row, col])
    # azimut approx depuis northness seul indisponible → libellé via northness
    if slope < 3.0:
        expo = "Terrain plat / replat"
    elif north > 0.35:
        expo = "Versant nord"
    elif north < -0.35:
        expo = "Versant sud"
    else:
        expo = "Versant est/ouest"
    return {"altitude": None if not np.isfinite(alt) else round(float(alt), 0),
            "slope_pct": round(slope, 1), "exposition": expo,
            "northness": round(north, 2), "source": "grille (Open-Meteo)"}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "bake":
        print("Baking altitude grid (IGN RGE ALTI)…")
        g = build_terrain_static(force=True)
        if g is None:
            print("  Open-Meteo unreachable — no terrain built.")
            sys.exit(1)
        a = g["altitude"]; v = a[np.isfinite(a)]
        print(f"  altitude  shape={a.shape} min={v.min():.0f} mean={v.mean():.0f} max={v.max():.0f} m")
        print(f"  slope     mean={np.nanmean(g['slope']):.1f}% max={np.nanmax(g['slope']):.0f}%")
        print(f"  northness range=({np.nanmin(g['northness']):.2f}..{np.nanmax(g['northness']):.2f})")
    else:
        lat, lon = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 else (45.9, 6.8)
        print(f"terrain_at_point({lat},{lon}) =", terrain_at_point(lat, lon))
