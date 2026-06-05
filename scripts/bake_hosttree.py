#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bake de la COMPOSITION FORESTIÈRE (arbre-hôte) sur la grille Sporia.

L'essence (feuillu / conifère / mixte) est le prédicteur écologique manquant pour
les champignons ectomycorhiziens : la trompette de la mort (hêtre/chêne) était
indistinguable d'une plantation d'épicéas tant qu'on ne connaissait que la densité
de forêt. Validé empiriquement (Boyce trompette 0.09→0.38, chanterelle 0.27→0.96, etc.).

Source : Copernicus Global Land Cover 100 m (CGLS-LC100 v3, 2019, Zenodo, sans auth),
couche « Forest-Type » (1=conifère persistant, 2=feuillu persistant, 3=conifère
caduc, 4=feuillu caduc, 5=mixte, 0=non-forêt, 255=nodata). Lue en streaming fenêtré
via /vsicurl (le fichier global de 1 Go n'est PAS téléchargé), agrégée en FRACTION
de cellule 0.01°.

Sortie : data/cache/host_broadleaf/needleleaf/mixed.npy — repris AUTOMATIQUEMENT par
train_sdm.py (hook host_*.npy).
Usage : python scripts/bake_hosttree.py [--force]
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window, from_bounds

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ["CPL_VSIL_CURL_USE_HEAD"] = "NO"          # Zenodo : HEAD sans accept-ranges
os.environ["GDAL_HTTP_MULTIRANGE"] = "NO"            # évite l'erreur de lecture d'index de tuiles
os.environ["GDAL_HTTP_MERGE_CONSECUTIVE_RANGES"] = "YES"
os.environ.setdefault("VSI_CACHE", "TRUE")
os.environ.setdefault("GDAL_CACHEMAX", "512")

GRID_H, GRID_W, RES = 1051, 1601, 0.01
LON0, LAT0 = -5.5, 51.5
BBOX = (-5.5, 10.5, 41.0, 51.5)
CACHE = Path("data/cache")
CGLS = ("/vsicurl/https://zenodo.org/api/records/3939050/files/"
        "PROBAV_LC100_global_v3.0.1_2019-nrt_Forest-Type-layer_EPSG-4326.tif/content")
HOST = {"broadleaf": (2, 4), "needleleaf": (1, 3), "mixed": (5,)}   # codes Forest-Type


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    paths = {k: CACHE / f"host_{k}.npy" for k in HOST}
    if not a.force and all(p.exists() for p in paths.values()):
        print("Couches host_*.npy déjà présentes (--force pour re-baker).")
        return

    print("Bake arbre-hôte (CGLS-LC100 Forest-Type, streaming fenêtré)…", flush=True)
    counts = {k: np.zeros(GRID_H * GRID_W, np.float64) for k in HOST}
    total = np.zeros(GRID_H * GRID_W, np.float64)
    with rasterio.open(CGLS) as ds:
        W = from_bounds(BBOX[0], BBOX[2], BBOX[1], BBOX[3], ds.transform)
        col0, row0, ww, wh = int(W.col_off), int(W.row_off), int(W.width), int(W.height)
        tr = ds.window_transform(Window(col0, row0, ww, wh))
        lon = np.array([tr * (j + 0.5, 0) for j in range(ww)])[:, 0]
        BLK = 512
        for i0 in range(0, wh, BLK):
            h = min(BLK, wh - i0)
            for attempt in range(4):
                try:
                    arr = ds.read(1, window=Window(col0, row0 + i0, ww, h)); break
                except Exception:
                    if attempt == 3:
                        raise
            lat = np.array([tr * (0, i0 + i + 0.5) for i in range(h)])[:, 1]
            LON, LAT = np.meshgrid(lon, lat)
            col = np.round((LON.ravel() - LON0) / RES).astype(np.int32)
            row = np.round((LAT0 - LAT.ravel()) / RES).astype(np.int32)
            flat = arr.ravel()
            inb = (row >= 0) & (row < GRID_H) & (col >= 0) & (col < GRID_W) & (flat != 255)
            gidx = (row * GRID_W + col)[inb]
            total += np.bincount(gidx, minlength=GRID_H * GRID_W)
            cls = flat[inb]
            for k, codes in HOST.items():
                m = np.isin(cls, codes)
                if m.any():
                    counts[k] += np.bincount(gidx[m], minlength=GRID_H * GRID_W)
            print(f"  bande lat {i0}/{wh} ({100*i0//wh} %)", flush=True)

    have = total > 0
    print(f"{100*have.mean():.0f} % de cellules couvertes.")
    for k in HOST:
        frac = np.full(GRID_H * GRID_W, np.nan, np.float32)
        frac[have] = (counts[k][have] / total[have]).astype(np.float32)
        np.save(paths[k], frac.reshape(GRID_H, GRID_W))
        print(f"  host_{k:10s} → {paths[k].name}  moyenne {np.nanmean(frac):.3f}")
    print("\nFait. train_sdm.py reprendra ces couches automatiquement (hook host_*.npy).")


if __name__ == "__main__":
    main()
