#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pré-télécharge les tuiles BD Forêt® WMTS (IGN) dans le cache disque permanent
(data/cache/foresttiles/z/x/y.png) pour que le « Radar à champignons » rende ses contours
NETS (pixel-exacts) SANS aucun appel réseau en régime permanent.

On ne récupère QUE les tuiles qui contiennent de la forêt (d'après le masque baké
forest_mask.npz) → pas de gaspillage sur l'océan / les zones sans forêt.

Volumes (France métropolitaine, ~12 Ko/tuile) :
    z6–z12 : ~17 000 tuiles (~200 Mo)
    z13    : +50 000 tuiles (~580 Mo)   → cumul ~780 Mo
    z14+   : explose (Go) — d'où le plafond par défaut à z13 (= maxNativeZoom du radar).

Usage :
    python scripts/bake_forest_tiles.py [--zmin 6] [--zmax 13] [--workers 8]

Idempotent : les tuiles déjà présentes sont ignorées → relançable / reprend où ça s'est
arrêté. À lancer une fois par serveur (dont la PROD), ou scp du dossier foresttiles/.
"""
from __future__ import annotations
import argparse
import io
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import champi_core as c

WMTS = ("https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
        "&LAYER=LANDCOVER.FORESTINVENTORY.V2&STYLE=normal&TILEMATRIXSET=PM"
        "&FORMAT=image/png&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}")


def forest_tiles(zmin, zmax):
    """Liste des (z, x, y) dont la tuile recouvre de la forêt (d'après le masque baké)."""
    fm = c._forest_mask()
    if fm is None:
        print("ERREUR : masque forêt non baké (data/cache/forest_mask.npz absent).")
        sys.exit(1)
    mask, (mw, ms, me, mn), _ = fm
    H, W = mask.shape
    px = (me - mw) / W
    py = (mn - ms) / H
    W3 = c._WORLD_3857
    out = []
    for z in range(zmin, zmax + 1):
        n = 2 ** z
        size = 2 * W3 / n
        x0 = int((mw + W3) / size); x1 = int((me + W3) / size)
        y0 = int((W3 - mn) / size); y1 = int((W3 - ms) / size)
        z_count = 0
        for tx in range(x0, x1 + 1):
            tw = -W3 + tx * size; te = tw + size
            c0 = max(0, int((tw - mw) / px)); c1 = min(W, int(math.ceil((te - mw) / px)))
            if c1 <= c0:
                continue
            for ty in range(y0, y1 + 1):
                tn = W3 - ty * size; ts = tn - size
                r0 = max(0, int((mn - tn) / py)); r1 = min(H, int(math.ceil((mn - ts) / py)))
                if r1 > r0 and mask[r0:r1, c0:c1].any():
                    out.append((z, tx, ty)); z_count += 1
        print(f"  z{z}: {z_count} tuiles forêt", flush=True)
    return out


def fetch_one(zxy, session):
    z, x, y = zxy
    fp = c._FOREST_TILE_DIR / str(z) / str(x) / f"{y}.png"
    if fp.exists():
        return "skip"
    url = WMTS.format(z=z, x=x, y=y)
    for attempt in range(4):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1)); continue
            if r.status_code != 200 or "image" not in r.headers.get("content-type", ""):
                return "miss"
            # On ne garde que le canal alpha (PNG 'L') → cache ~6× plus léger.
            alpha = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGBA"))[..., 3]
            fp.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(alpha, "L").save(fp, format="PNG", optimize=True)
            return "ok"
        except Exception:
            time.sleep(2 * (attempt + 1))
    return "fail"


def convert_one(fp: Path):
    """Convertit une tuile RGBA déjà téléchargée en alpha-seul (mode 'L'), en place.
    Idempotent : ignore les tuiles déjà en 'L'."""
    try:
        im = Image.open(fp)
        if im.mode == "L":
            return "skip"
        alpha = np.asarray(im.convert("RGBA"))[..., 3]
        Image.fromarray(alpha, "L").save(fp, format="PNG", optimize=True)
        return "ok"
    except Exception:
        return "fail"


def run_convert(workers):
    """Convertit tout le cache foresttiles/ en alpha-seul (local, sans réseau)."""
    files = list(c._FOREST_TILE_DIR.rglob("*.png"))
    total = len(files)
    print(f"Conversion alpha-seul : {total} tuiles…", flush=True)
    t0 = time.time()
    counts = {"ok": 0, "skip": 0, "fail": 0}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        done = 0
        for res in ex.map(convert_one, files):
            counts[res] += 1
            done += 1
            if done % 2000 == 0 or done == total:
                print(f"  {done}/{total}  {counts}", flush=True)
    print(f"[OK] conversion terminée en {(time.time()-t0)/60:.1f} min : {counts}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zmin", type=int, default=6)
    ap.add_argument("--zmax", type=int, default=13)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--convert", action="store_true",
                    help="convertit le cache existant en alpha-seul (local, sans téléchargement)")
    a = ap.parse_args()

    if a.convert:
        run_convert(a.workers)
        return

    print(f"Recensement des tuiles forêt z{a.zmin}–z{a.zmax}…", flush=True)
    tiles = forest_tiles(a.zmin, a.zmax)
    total = len(tiles)
    print(f"Total : {total} tuiles à vérifier ({total * 12 / 1024:.0f} Mo max).", flush=True)

    t0 = time.time()
    counts = {"ok": 0, "skip": 0, "miss": 0, "fail": 0}
    session = requests.Session()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(fetch_one, t, session): t for t in tiles}
        done = 0
        for fut in as_completed(futs):
            counts[fut.result()] += 1
            done += 1
            if done % 500 == 0 or done == total:
                el = time.time() - t0
                rate = done / el if el else 0
                eta = (total - done) / rate if rate else 0
                print(f"  {done}/{total}  ok={counts['ok']} skip={counts['skip']} "
                      f"miss={counts['miss']} fail={counts['fail']}  "
                      f"{rate:.0f} t/s  ETA {eta/60:.0f} min", flush=True)
    print(f"[OK] terminé en {(time.time()-t0)/60:.1f} min : {counts}", flush=True)


if __name__ == "__main__":
    main()
