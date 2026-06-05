#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bake d'une couche d'OCCUPATION DU SOL sur la grille Sporia (#B SDM).

But : donner aux SDM les milieux NON forestiers (prairies, cultures, landes,
zones humides) qui manquaient — les espèces de milieu ouvert (morille, mousseron,
rosé, lépiste…) étaient à Boyce ≤ 0 car nos couches étaient forêt/sol/relief/climat.

Source : ESA WorldCover 2021 v200 (10 m, classé, sans authentification) sur AWS S3.
Astuce : les tuiles sont des COG EPSG:4326 avec overviews → on lit une version
DÉCIMÉE (~80 m) en streaming via /vsicurl (quelques Mo/tuile, pas les 74 Mo),
puis on agrège en FRACTION DE CLASSE par cellule de 0.01° (~1,1 km : ~190 sous-
pixels/cellule).

Sortie : data/cache/lc_<classe>.npy (fraction ∈ [0,1], NaN hors données) — repris
AUTOMATIQUEMENT par train_sdm.py (hook lc_*.npy). Classes bakées :
  lc_tree    couvert arboré (10)   — recoupe forest_density (cross-check)
  lc_shrub   arbustes/landes (20)
  lc_grass   prairies (30)
  lc_crop    cultures (40)
  lc_built   artificialisé (50)    — proxy lisière urbaine / biais d'effort
  lc_wetland zones humides herbacées (90)

Usage : python scripts/bake_landcover.py [--ov 8] [--force]
Dépend de rasterio + numpy.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling

# perf /vsicurl
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
os.environ.setdefault("VSI_CACHE", "TRUE")

GRID_H, GRID_W, RES = 1051, 1601, 0.01
LON0, LAT0 = -5.5, 51.5                  # centre de la cellule (0,0)
BBOX = (-5.5, 10.5, 41.0, 51.5)          # lon_min, lon_max, lat_min, lat_max
CACHE = Path("data/cache")
BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"

# code WorldCover → nom de sortie lc_<nom>.npy
WANT = {10: "tree", 20: "shrub", 30: "grass", 40: "crop", 50: "built", 90: "wetland"}


def tiles_for_bbox():
    """Tuiles WorldCover 3° (coin SO) couvrant la bbox France."""
    lon_corners = range(-6, 12, 3)       # -6,-3,0,3,6,9 → couvre -5.5..10.5
    lat_corners = range(39, 54, 3)       # 39,42,45,48,51 → couvre 41..51.5
    out = []
    for lat in lat_corners:
        for lon in lon_corners:
            if lon + 3 <= BBOX[0] or lon >= BBOX[1] or lat + 3 <= BBOX[2] or lat >= BBOX[3]:
                continue
            ns = f"N{lat:02d}" if lat >= 0 else f"S{-lat:02d}"
            ew = f"E{lon:03d}" if lon >= 0 else f"W{-lon:03d}"
            out.append(f"{ns}{ew}")
    return out


def cell_rc(lon, lat):
    col = np.round((lon - LON0) / RES).astype(np.int32)
    row = np.round((LAT0 - lat) / RES).astype(np.int32)
    return row, col


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ov", type=int, default=8,
                    help="facteur de décimation (8 ≈ 80 m, 16 ≈ 160 m)")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    targets = {n: CACHE / f"lc_{n}.npy" for n in WANT.values()}
    if not a.force and all(p.exists() for p in targets.values()):
        print("Toutes les couches lc_*.npy déjà présentes (--force pour re-baker).")
        return

    counts = {n: np.zeros((GRID_H, GRID_W), np.float64) for n in WANT.values()}
    total = np.zeros((GRID_H, GRID_W), np.float64)

    tiles = tiles_for_bbox()
    print(f"Occupation du sol WorldCover 2021 — {len(tiles)} tuiles candidates "
          f"(décimation ×{a.ov} ≈ {a.ov*10} m)")
    used = 0
    for tname in tiles:
        url = f"/vsicurl/{BASE}/ESA_WorldCover_10m_2021_v200_{tname}_Map.tif"
        try:
            with rasterio.open(url) as ds:
                h, w = ds.height // a.ov, ds.width // a.ov
                arr = ds.read(1, out_shape=(h, w), resampling=Resampling.nearest)
                left, bottom, right, top = ds.bounds
        except Exception as e:
            print(f"  {tname:8s} : absent/illisible ({type(e).__name__})")
            continue
        used += 1
        lon = left + (np.arange(w) + 0.5) * (right - left) / w
        lat = top - (np.arange(h) + 0.5) * (top - bottom) / h
        LON, LAT = np.meshgrid(lon, lat)
        row, col = cell_rc(LON.ravel(), LAT.ravel())
        flat = arr.ravel()
        inb = (row >= 0) & (row < GRID_H) & (col >= 0) & (col < GRID_W) & (flat != 0)
        gidx = (row * GRID_W + col)[inb]
        np.add.at(total.ravel(), gidx, 1.0)
        cls = flat[inb]
        for code, name in WANT.items():
            sel = gidx[cls == code]
            if sel.size:
                np.add.at(counts[name].ravel(), sel, 1.0)
        print(f"  {tname:8s} : {arr.size/1e6:.1f} Mpx lus, "
              f"{inb.sum()/1e6:.1f} M en grille", flush=True)

    have = total > 0
    print(f"\n{used} tuiles utilisées ; {100*have.mean():.0f} % de cellules couvertes.")
    for code, name in WANT.items():
        frac = np.full((GRID_H, GRID_W), np.nan, np.float32)
        frac[have] = (counts[name][have] / total[have]).astype(np.float32)
        np.save(targets[name], frac)
        print(f"  lc_{name:8s} → {targets[name].name}  "
              f"moyenne {np.nanmean(frac):.3f}, max {np.nanmax(frac):.2f}")
    print("\nFait. train_sdm.py reprendra ces couches automatiquement (hook lc_*.npy).")


if __name__ == "__main__":
    main()
