#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bake d'une couche FORÊT-TYPE européenne (feuillu/conifère/mixte) sur la grille Sporia,
depuis CGLS-LC100 Forest-Type (COG global, streamé en /vsicurl comme bake_landcover.py).
Donne un HÔTE GROSSIER pan-européen (≠ host_* BD Forêt, France-only) pour entraîner les
espèces ectomycorhiziennes sur le domaine transfrontalier.

Sorties : data/cache/fteu_broadleaf.npy, fteu_needleleaf.npy, fteu_mixed.npy (fraction ∈
[0,1] par cellule 0.01°, NaN hors données). Repris par train_sdm.py (hook fteu_*.npy).

Usage : python scripts/bake_foresttype_eu.py [--ov 1] [--force]
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path

import numpy as np

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,=1")

GRID_H, GRID_W, RES = 1051, 1601, 0.01
LON0, LAT0 = -5.5, 51.5
BBOX = (-5.5, 10.5, 41.0, 51.5)
CACHE = Path("data/cache")
URL = ("/vsicurl/https://zenodo.org/records/3939050/files/"
       "PROBAV_LC100_global_v3.0.1_2019-nrt_Forest-Type-layer_EPSG-4326.tif?download=1")
NODATA = 255
CLASS_GROUPS = {"fteu_broadleaf": {2, 4}, "fteu_needleleaf": {1, 3}, "fteu_mixed": {5}}


def accumulate_counts(codes, gidx, total, counts, groups):
    """Accumule EN PLACE le nb de pixels par cellule (total) et par groupe de classes
    (counts[nom]). Appelable par bandes → mémoire bornée. codes/gidx : 1D des pixels valides."""
    np.add.at(total, gidx, 1.0)
    for name, group in groups.items():
        sel = gidx[np.isin(codes, list(group))]
        if sel.size:
            np.add.at(counts[name], sel, 1.0)


def fractions_from_counts(total, counts):
    """total/counts (accumulés) → {nom: fraction (n_cells,), NaN si cellule vide}."""
    have = total > 0
    out = {}
    for name, cnt in counts.items():
        frac = np.full(total.shape, np.nan, np.float32)
        frac[have] = (cnt[have] / total[have]).astype(np.float32)
        out[name] = frac
    return out


def foresttype_fractions(codes, gidx, n_cells, groups):
    """Convenience (un seul lot) : accumulate_counts frais + fractions_from_counts. Utilisé
    par les tests ; le bake accumule par bandes."""
    total = np.zeros(n_cells, np.float64)
    counts = {name: np.zeros(n_cells, np.float64) for name in groups}
    accumulate_counts(codes, gidx, total, counts, groups)
    return fractions_from_counts(total, counts)


def cell_rc(lon, lat):
    col = np.round((lon - LON0) / RES).astype(np.int32)
    row = np.round((LAT0 - lat) / RES).astype(np.int32)
    return row, col


def main():
    import rasterio
    from rasterio.windows import from_bounds

    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    targets = {n: CACHE / f"{n}.npy" for n in CLASS_GROUPS}
    if not a.force and all(p.exists() for p in targets.values()):
        print("fteu_*.npy déjà présents (--force pour re-baker).")
        return

    from rasterio.windows import Window

    ncell = GRID_H * GRID_W
    total = np.zeros(ncell, np.float64)
    counts = {name: np.zeros(ncell, np.float64) for name in CLASS_GROUPS}
    print(f"Forêt-type CGLS — lecture fenêtre bbox par bandes depuis {URL[:60]}…", flush=True)
    with rasterio.open(URL) as ds:
        win = from_bounds(BBOX[0], BBOX[2], BBOX[1], BBOX[3], ds.transform)
        row_off, col_off = int(win.row_off), int(win.col_off)
        wh, ww = int(win.height), int(win.width)
        STRIP = 512  # lignes source par bande → mémoire bornée (~ww×STRIP pixels)
        for r0 in range(0, wh, STRIP):
            r1 = min(r0 + STRIP, wh)
            sub = Window(col_off, row_off + r0, ww, r1 - r0)
            arr = ds.read(1, window=sub)  # (r1-r0, ww) uint8, pleine résolution ~100 m
            wt = ds.window_transform(sub)
            lon = wt.c + (np.arange(ww) + 0.5) * wt.a
            lat = wt.f + (np.arange(r1 - r0) + 0.5) * wt.e
            LON, LAT = np.meshgrid(lon, lat)
            row, col = cell_rc(LON.ravel(), LAT.ravel())
            flat = arr.ravel()
            inb = ((row >= 0) & (row < GRID_H) & (col >= 0) & (col < GRID_W) & (flat != NODATA))
            accumulate_counts(flat[inb], row[inb] * GRID_W + col[inb], total, counts, CLASS_GROUPS)
            print(f"  bande {r0}-{r1}/{wh}", flush=True)
    fr = fractions_from_counts(total, counts)
    for name, frac in fr.items():
        np.save(targets[name], frac.reshape(GRID_H, GRID_W))
        finite = np.isfinite(frac)
        print(f"  {name} → {targets[name].name}  couverture {100*finite.mean():.0f}%, "
              f"moyenne {np.nanmean(frac):.3f}", flush=True)
    print("Fait. train_sdm.py reprendra fteu_*.npy (hook).")


if __name__ == "__main__":
    main()
