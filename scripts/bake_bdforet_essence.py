#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bake de la COMPOSITION FORESTIÈRE FINE (essence par genre) sur la grille Sporia.

Remplace l'arbre-hôte grossier en 3 classes (feuillu/conifère/mixte, issu de CGLS-LC100
100 m — cf. bake_hosttree.py) par les ESSENCES réelles de la BD Forêt® V2 (IGN) :
chênes, hêtre, châtaignier, peuplier, pins, sapin/épicéa, douglas… L'essence-hôte est
LE déterminant des champignons ectomycorhiziens (un cèpe sous chêne ≠ sous épicéa), et
la BD Forêt la porte au polygone — on ne l'exploitait jusqu'ici qu'au clic (forest_at_point).

Source : WFS data.geopf.fr, couche LANDCOVER.FORESTINVENTORY.V2:formation_vegetale
(champ `essence`). On pagine par TUILES alignées sur la grille (BBOX en EPSG:3857,
géométries renvoyées en EPSG:4326 lon/lat), on rasterise chaque tuile à 100 m, puis on
agrège en FRACTION de cellule 0.01° par groupe d'essence.

Sorties data/cache/host_*.npy — reprises AUTOMATIQUEMENT par train_sdm.py (hook host_*.npy) :
  fines  : host_chene, host_hetre, host_chataignier, host_peuplier, host_feuillus_autres,
           host_pin, host_sapin_epicea, host_douglas, host_coniferes_autres, host_mixte
  larges : host_broadleaf, host_needleleaf, host_mixed (compat. family_at_point), recalculés
           depuis la BD Forêt (plus précis et alignés que l'ancienne source CGLS).

Résumable : checkpoint disque tous les CKPT_EVERY tuiles (reprise après coupure réseau).
Usage : python scripts/bake_bdforet_essence.py [--force] [--tile-deg 0.5] [--fine 10]
"""
from __future__ import annotations
import argparse
import time
import unicodedata
from pathlib import Path

import numpy as np
import requests
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely.geometry import shape

# Grille de référence (identique aux rasters météo / mushroom_map).
GRID_W, GRID_H, RES = 1601, 1051, 0.01
GRID_LEFT, GRID_TOP = -5.505, 51.505            # coins (corner), pas centre
CACHE = Path("data/cache")
WFS = "https://data.geopf.fr/wfs/ows"
TYPENAME = "LANDCOVER.FORESTINVENTORY.V2:formation_vegetale"
CKPT = CACHE / "_bdforet_bake_ckpt.npz"
CKPT_EVERY = 25
PAGE = 5000                                     # plafond DUR du serveur geopf (numberReturned ≤ 5000)
                                                # → toute page pleine (== PAGE) implique de paginer.

_R = 6378137.0
def _lonlat_to_merc(lon, lat):
    import math
    x = lon * math.pi / 180.0 * _R
    y = math.log(math.tan(math.pi / 4.0 + lat * math.pi / 360.0)) * _R
    return x, y

# --- Groupes d'essence (ordre = index de classe pour la rasterisation) -------
GROUPS = ["chene", "hetre", "chataignier", "peuplier", "feuillus_autres",
          "pin", "sapin_epicea", "douglas", "coniferes_autres", "mixte"]
BROADLEAF = {"chene", "hetre", "chataignier", "peuplier", "feuillus_autres"}
NEEDLELEAF = {"pin", "sapin_epicea", "douglas", "coniferes_autres"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return s


def essence_group(essence: str) -> int | None:
    """Mappe le champ `essence` BD Forêt vers un index de GROUPS, ou None (à ignorer :
    NR/NC/sans couvert arboré)."""
    s = _norm(essence)
    if not s or "sans couvert" in s or s in ("nr", "nc"):
        return None
    if "chene" in s:
        return GROUPS.index("chene")
    if "hetre" in s:
        return GROUPS.index("hetre")
    if "chataignier" in s:
        return GROUPS.index("chataignier")
    if "peuplier" in s:
        return GROUPS.index("peuplier")
    if "douglas" in s:
        return GROUPS.index("douglas")
    # ATTENTION ordre : « sapin » contient la sous-chaîne « pin » → tester les conifères
    # spécifiques AVANT le « pin » générique, sinon « Sapin, épicéa » serait pris pour un pin.
    if "sapin" in s or "epicea" in s:
        return GROUPS.index("sapin_epicea")
    if "meleze" in s or "conifere" in s:
        return GROUPS.index("coniferes_autres")
    if "pin" in s:
        return GROUPS.index("pin")
    if "mixte" in s:
        return GROUPS.index("mixte")
    if "robinier" in s or "feuillus" in s:
        return GROUPS.index("feuillus_autres")
    return GROUPS.index("feuillus_autres")      # feuillu non listé → autres feuillus


def fetch_tile(west, south, east, north):
    """Toutes les géométries (lon/lat) + groupe d'essence d'une tuile (BBOX 3857,
    paginé). Renvoie liste de (shapely_geom, group_idx). [] si vide."""
    wx, sy = _lonlat_to_merc(west, south)
    ex, ny = _lonlat_to_merc(east, north)
    out, start = [], 0
    while True:
        params = {
            "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
            "TYPENAMES": TYPENAME, "SRSNAME": "EPSG:4326",
            "BBOX": f"{wx},{sy},{ex},{ny},EPSG:3857",
            "COUNT": PAGE, "STARTINDEX": start, "outputFormat": "application/json",
        }
        j = None
        for attempt in range(4):
            try:
                r = requests.get(WFS, params=params, timeout=90)
                r.raise_for_status()
                j = r.json()
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(4 * (attempt + 1))
        feats = j.get("features", [])
        for f in feats:
            gi = essence_group(f.get("properties", {}).get("essence", ""))
            if gi is None or not f.get("geometry"):
                continue
            try:
                out.append((shape(f["geometry"]), gi))
            except Exception:
                pass
        if len(feats) < PAGE:
            break
        start += PAGE
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--tile-deg", type=float, default=0.5)
    ap.add_argument("--fine", type=int, default=10, help="sous-échantillonnage par cellule (10 = 100 m)")
    ap.add_argument("--one-tile", help="DEBUG : 'c0,r0' (indices de cellule) → une seule tuile, pas d'écriture")
    a = ap.parse_args()

    fine_targets = [CACHE / f"host_{g}.npy" for g in GROUPS]
    if not a.force and not a.one_tile and all(p.exists() for p in fine_targets):
        print("Couches host_<essence>.npy déjà présentes (--force pour re-baker).")
        return

    F = a.fine
    step = int(round(a.tile_deg / RES))         # cellules par tuile
    counts = np.zeros((len(GROUPS), GRID_H, GRID_W), np.float64)
    done = set()
    if CKPT.exists() and not a.force and not a.one_tile:
        z = np.load(CKPT, allow_pickle=True)
        counts = z["counts"]
        done = set(tuple(t) for t in z["done"])
        print(f"Reprise checkpoint : {len(done)} tuiles déjà faites.")

    tiles = [(c0, r0) for r0 in range(0, GRID_H, step) for c0 in range(0, GRID_W, step)]
    if a.one_tile:
        c0, r0 = (int(x) for x in a.one_tile.split(","))
        tiles = [(c0, r0)]

    t_start = time.time()
    for n, (c0, r0) in enumerate(tiles, 1):
        if (c0, r0) in done:
            continue
        c1, r1 = min(c0 + step, GRID_W), min(r0 + step, GRID_H)
        west = GRID_LEFT + c0 * RES
        east = GRID_LEFT + c1 * RES
        north = GRID_TOP - r0 * RES
        south = GRID_TOP - r1 * RES
        try:
            polys = fetch_tile(west, south, east, north)
        except Exception as e:
            print(f"  tuile ({c0},{r0}) ÉCHEC réseau : {e} — on garde pour reprise", flush=True)
            continue
        if polys:
            fh, fw = (r1 - r0) * F, (c1 - c0) * F
            tr = from_origin(west, north, RES / F, RES / F)
            # label 0=vide, sinon group_idx+1
            label = rasterize([(g, gi + 1) for g, gi in polys], out_shape=(fh, fw),
                              transform=tr, fill=0, dtype="int32", all_touched=False)
            for gi in range(len(GROUPS)):
                m = (label == gi + 1)
                if not m.any():
                    continue
                # agrège les blocs F×F → comptes de pixels fins par cellule
                blk = m.reshape(r1 - r0, F, c1 - c0, F).sum(axis=(1, 3))
                counts[gi, r0:r1, c0:c1] += blk
        done.add((c0, r0))
        if a.one_tile:
            tot = counts.sum(0)[r0:r1, c0:c1]
            print(f"DEBUG tuile ({c0},{r0}) : {len(polys)} polygones, "
                  f"{int((tot>0).sum())} cellules forêt")
            for gi, g in enumerate(GROUPS):
                cc = counts[gi, r0:r1, c0:c1]
                if cc.sum() > 0:
                    print(f"   {g:18s} {int(cc.sum()):8d} px fins")
            return
        if n % 10 == 0 or n == len(tiles):
            el = time.time() - t_start
            print(f"  {n}/{len(tiles)} tuiles ({100*n//len(tiles)} %) — {len(polys)} pol. "
                  f"dernière — {el:.0f}s", flush=True)
        if len(done) % CKPT_EVERY == 0:
            np.savez(CKPT, counts=counts, done=np.array(list(done)))

    # --- Écriture des fractions ------------------------------------------------
    total = counts.sum(axis=0)                  # px hôte par cellule (partition → pas de double compte)
    have = total > 0
    print(f"\n{100*have.mean():.1f} % de cellules avec forêt classée.")
    for gi, g in enumerate(GROUPS):
        frac = np.full((GRID_H, GRID_W), np.nan, np.float32)
        frac[have] = (counts[gi][have] / total[have]).astype(np.float32)
        np.save(CACHE / f"host_{g}.npy", frac)
        print(f"  host_{g:18s} → moyenne {np.nanmean(frac):.3f}")

    # Couches LARGES (compat. mushroom_map.family_at_point) recalculées depuis la BD Forêt.
    for name, members in (("broadleaf", BROADLEAF), ("needleleaf", NEEDLELEAF), ("mixed", {"mixte"})):
        idx = [GROUPS.index(m) for m in members]
        frac = np.full((GRID_H, GRID_W), np.nan, np.float32)
        frac[have] = (counts[idx][:, have].sum(0) / total[have]).astype(np.float32)
        np.save(CACHE / f"host_{name}.npy", frac)
        print(f"  host_{name:18s} → moyenne {np.nanmean(frac):.3f}")

    if CKPT.exists():
        CKPT.unlink()
    print("\nFait. train_sdm.py reprendra ces couches automatiquement (hook host_*.npy).")


if __name__ == "__main__":
    main()
