#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bake des NORMALES BIOCLIMATIQUES WorldClim v2.1 sur la grille Sporia (#3 SDM).

But : remplacer les proxys géographiques lat/lon (qui dominaient les SDM et
provoquaient un sur-apprentissage spatial) par de vraies variables climatiques.

Source : WorldClim 2.1 (https://worldclim.org), normales 1970-2000, 19 variables
« bioclim ». On télécharge la zip globale (mise en cache disque), on découpe les
variables utiles et on les rééchantillonne (bilinéaire) sur la grille de l'app
(EPSG:4326, 1601×1051, cellule 0.01°, centre haut-gauche -5.5 lon / 51.5 lat).

Sortie : data/cache/clim_<nom>.npy — repris AUTOMATIQUEMENT par train_sdm.py
(hook clim_*.npy). Variables bakées :
  bio1  T° moyenne annuelle (°C)
  bio4  saisonnalité thermique (écart-type ×100)
  bio6  T° min. du mois le plus froid (°C)
  bio12 précipitations annuelles (mm)
  bio15 saisonnalité des précip. (coef. variation)
  bio18 précip. du trimestre le plus chaud (mm)

Usage : python scripts/bake_worldclim.py [--res 2.5m|5m|10m] [--force]
Dépend de rasterio + requests.
"""
from __future__ import annotations
import argparse
import sys
import zipfile
from pathlib import Path

import numpy as np
import requests
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_origin

GRID_H, GRID_W, RES = 1051, 1601, 0.01
LON0, LAT0 = -5.5, 51.5                       # centre de la cellule (0,0)
# Raster nord-haut : coin haut-gauche = centre de (0,0) décalé d'une demi-cellule.
DST_TRANSFORM = from_origin(LON0 - RES / 2, LAT0 + RES / 2, RES, RES)
DST_CRS = "EPSG:4326"

CACHE = Path("data/cache")
WC_DIR = CACHE / "worldclim"
BASE_URL = "https://geodata.ucdavis.edu/climate/worldclim/2_1/base"

# variable bioclim → nom de sortie clim_<nom>.npy
#   bio5  T° max du mois le plus chaud (stress thermique estival, espèces thermophiles)
#   bio17 précip. du trimestre le plus sec (sécheresse estivale → mémoire hydrique)
WANT = {1: "bio1", 4: "bio4", 5: "bio5", 6: "bio6",
        12: "bio12", 15: "bio15", 17: "bio17", 18: "bio18"}


def download_zip(res: str) -> Path:
    WC_DIR.mkdir(parents=True, exist_ok=True)
    zp = WC_DIR / f"wc2.1_{res}_bio.zip"
    if zp.exists() and zp.stat().st_size > 1_000_000:
        print(f"  zip déjà présente ({zp.stat().st_size/1e6:.0f} Mo) : {zp}")
        return zp
    url = f"{BASE_URL}/wc2.1_{res}_bio.zip"
    print(f"  téléchargement {url}")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        done, step = 0, 0
        tmp = zp.with_suffix(".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total and done // (50 << 20) > step:      # tous les ~50 Mo
                    step = done // (50 << 20)
                    print(f"    {done/1e6:.0f}/{total/1e6:.0f} Mo "
                          f"({100*done//total} %)", flush=True)
        tmp.rename(zp)
    print(f"  téléchargé : {zp.stat().st_size/1e6:.0f} Mo")
    return zp


def reproject_tif(src_path_or_bytes, src_name) -> np.ndarray:
    """Rééchantillonne un GeoTIFF WorldClim sur la grille de l'app → array float32
    (NaN hors données / mer)."""
    with rasterio.open(src_path_or_bytes) as src:
        src_nodata = src.nodata
        dst = np.full((GRID_H, GRID_W), np.nan, np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=dst,
            src_transform=src.transform, src_crs=src.crs,
            dst_transform=DST_TRANSFORM, dst_crs=DST_CRS,
            src_nodata=src_nodata, dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
    # WorldClim nodata = grand négatif ; tout résidu aberrant → NaN
    dst[dst < -1e30] = np.nan
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", default="2.5m", choices=["2.5m", "5m", "10m"],
                    help="résolution WorldClim (défaut 2.5m ≈ 4,6 km)")
    ap.add_argument("--force", action="store_true", help="re-bake même si présent")
    a = ap.parse_args()

    targets = {n: CACHE / f"clim_{n}.npy" for n in WANT.values()}
    if not a.force and all(p.exists() for p in targets.values()):
        print("Toutes les couches clim_*.npy déjà présentes (--force pour re-baker).")
        return

    print(f"Bake WorldClim {a.res} → grille {GRID_W}×{GRID_H}")
    zp = download_zip(a.res)
    with zipfile.ZipFile(zp) as z:
        names = z.namelist()
        for num, out_name in WANT.items():
            out = targets[out_name]
            if out.exists() and not a.force:
                print(f"  {out_name} déjà baké"); continue
            tif = next((n for n in names if n.endswith(f"bio_{num}.tif")), None)
            if tif is None:
                print(f"  [!] {out_name} : tif bio_{num} introuvable dans la zip"); continue
            # rasterio lit l'entrée zip via /vsizip/
            vsi = f"/vsizip/{zp.as_posix()}/{tif}"
            arr = reproject_tif(vsi, tif)
            np.save(out, arr)
            valid = np.isfinite(arr)
            print(f"  {out_name:6s} → {out.name}  "
                  f"[{np.nanmin(arr):.1f}..{np.nanmax(arr):.1f}], "
                  f"{100*valid.mean():.0f} % cellules valides")
    print("\nFait. train_sdm.py reprendra ces couches automatiquement (hook clim_*.npy).")


if __name__ == "__main__":
    main()
