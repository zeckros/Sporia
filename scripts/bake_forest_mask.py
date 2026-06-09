#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bake d'un masque forêt (BD Forêt® V2, IGN) pour clipper le « Radar à champignons » aux
contours réels des forêts — même source que le calque forêt affiché → cohérence parfaite.

Principe : on interroge le WMS BD Forêt par grandes dalles (forêt = pixel opaque,
hors-forêt = transparent), on en déduit un masque binaire sur une grille Web Mercator
(EPSG:3857) couvrant la France métropolitaine, enregistré dans data/cache/forest_mask.npz.

Usage :
    python scripts/bake_forest_mask.py [--px 400]

~6 requêtes WMS, quelques minutes. À relancer seulement si BD Forêt évolue (rare).
La résolution (--px) est volontairement plafonnée (~400 m) car l'overlay est un PNG
unique : un pas plus fin alourdit l'image décodée côté navigateur (passer aux tuiles
si l'on veut des contours pixel-exacts à tous les zooms).
"""
from __future__ import annotations
import argparse
import io
import math
import time
from pathlib import Path

import numpy as np
import requests
from PIL import Image

WMS = "https://data.geopf.fr/wms-r/wms"
LAYER = "LANDCOVER.FORESTINVENTORY.V2"
# France métropolitaine (marge incluse), en lon/lat → converti en 3857
LON_MIN, LON_MAX = -5.25, 9.65
LAT_MIN, LAT_MAX = 41.30, 51.15
R = 6378137.0
CHUNK = 2048          # px max par requête WMS (testé jusqu'à 4096)
ALPHA_FOREST = 10     # alpha > seuil ⇒ pixel forêt
OUT = Path("data/cache/forest_mask.npz")


def _merc(lon, lat):
    x = math.radians(lon) * R
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R
    return x, y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--px", type=float, default=400.0, help="taille de pixel (m)")
    px = ap.parse_args().px

    west, south = _merc(LON_MIN, LAT_MIN)
    east, north = _merc(LON_MAX, LAT_MAX)
    W = int(math.ceil((east - west) / px))
    H = int(math.ceil((north - south) / px))
    east = west + W * px          # ré-aligne l'extent sur la grille entière
    south = north - H * px
    print(f"Masque forêt : {W}x{H} px à {px:.0f} m  ({W*H/1e6:.0f} Mpx)")
    mask = np.zeros((H, W), dtype=bool)

    cols = list(range(0, W, CHUNK))
    rows = list(range(0, H, CHUNK))
    total = len(cols) * len(rows)
    done = 0
    for cy in rows:
        h = min(CHUNK, H - cy)
        for cx in cols:
            w = min(CHUNK, W - cx)
            bx0 = west + cx * px
            bx1 = west + (cx + w) * px
            by1 = north - cy * px            # haut de la dalle (row cy)
            by0 = north - (cy + h) * px
            params = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap",
                      "LAYERS": LAYER, "STYLES": "normal", "FORMAT": "image/png",
                      "TRANSPARENT": "true", "CRS": "EPSG:3857",
                      "WIDTH": w, "HEIGHT": h, "BBOX": f"{bx0},{by0},{bx1},{by1}"}
            ok = False
            for attempt in range(4):
                try:
                    r = requests.get(WMS, params=params, timeout=180)
                    r.raise_for_status()
                    a = np.array(Image.open(io.BytesIO(r.content)).convert("RGBA"))[..., 3]
                    mask[cy:cy + h, cx:cx + w] = a > ALPHA_FOREST
                    ok = True
                    break
                except Exception as e:
                    if attempt == 3:
                        print(f"  ECHEC dalle ({cx},{cy}): {e}")
                    time.sleep(3 * (attempt + 1))
            done += 1
            pct = mask[cy:cy + h, cx:cx + w].mean() * 100 if ok else 0
            print(f"  dalle {done}/{total} {'OK' if ok else 'KO'}  ({pct:.0f}% foret)", flush=True)
            time.sleep(0.3)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT, packed=np.packbits(mask), shape=np.array([H, W]),
                        bounds=np.array([west, south, east, north]), px=np.array([px]))
    print(f"[OK] {OUT}  ({OUT.stat().st_size/1e6:.1f} Mo)  foret = {mask.mean()*100:.1f}% de la grille")


if __name__ == "__main__":
    main()
