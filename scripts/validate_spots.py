#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validation du modèle contre les COINS ENREGISTRÉS par les utilisateurs (vérité terrain).

Jusqu'ici le modèle n'était validé que sur un holdout GBIF (Boyce/AUC) — qui souffre du
même biais d'échantillonnage que l'entraînement. Les spots de data/user_spots.json sont
des coins RÉELLEMENT productifs : on teste si la suitabilité d'habitat (SDM, agrégée sur
les espèces) y est plus élevée que sur des mailles forestières tirées au hasard.

Métriques :
  • percentile de chaque spot dans la distribution d'habitat des mailles forêt ;
  • AUC = P(habitat[spot] > habitat[maille forêt aléatoire]) — 0.5 = hasard, 1 = parfait ;
  • même chose pour le radar du jour (habitat × pousse) si la météo récente est en cache.

Sert de baromètre AVANT/APRÈS l'ajout de prédicteurs (rejouer après chaque retrain).
Usage : python scripts/validate_spots.py [--date YYYYMMDD] [--label "avant retrain"]
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mushroom_map as mmap                       # noqa: E402
import champi_core as core                        # noqa: E402
import fruiting_live as fl                        # noqa: E402

CACHE = Path("data/cache")
GRID_H, GRID_W, RES = 1051, 1601, 0.01
LON0, LAT0 = -5.5, 51.5
SPOTS_JSON = Path("data/user_spots.json")
FOREST_MIN = 0.10


def load_spots():
    if not SPOTS_JSON.exists():
        sys.exit("data/user_spots.json absent.")
    d = json.loads(SPOTS_JSON.read_text(encoding="utf-8"))
    out = []
    for user, blob in d.items():
        for s in blob.get("spots", []):
            if "lat" in s and "lon" in s:
                out.append((user, s.get("name", "?"), float(s["lat"]), float(s["lon"])))
    return out


def rc(lat, lon):
    return int(round((LAT0 - lat) / RES)), int(round((lon - LON0) / RES))


def habitat_grid():
    """Max des SDM d'habitat sur toutes les espèces (le « où » indépendant du moment)."""
    grids = []
    for p in sorted(CACHE.glob("sdm_*.npy")):
        if p.stem == "sdm_bg_target_cells":
            continue
        try:
            grids.append(np.load(p))
        except Exception:
            pass
    if not grids:
        return None
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmax(np.stack(grids), axis=0).astype(np.float32)


def auc_and_pct(grid, spots, forest):
    """AUC (proba qu'un spot dépasse une maille forêt aléatoire) + percentiles."""
    null = grid[forest & np.isfinite(grid)]
    if null.size == 0:
        return None
    null_sorted = np.sort(null)
    rows = []
    aucs = []
    for user, name, lat, lon in spots:
        r, c = rc(lat, lon)
        if not (0 <= r < GRID_H and 0 <= c < GRID_W):
            rows.append((name, None, None)); continue
        v = grid[r, c]
        if not np.isfinite(v):
            rows.append((name, None, None)); continue
        pct = float(np.searchsorted(null_sorted, v) / null_sorted.size)
        rows.append((name, float(v), pct))
        aucs.append(pct)                              # P(v > random) = percentile
    return rows, (float(np.mean(aucs)) if aucs else None), null.size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYYMMDD pour le radar (défaut : aujourd'hui)")
    ap.add_argument("--label", default="", help="étiquette affichée (ex. 'avant retrain')")
    a = ap.parse_args()

    spots = load_spots()
    dens = mmap.load_forest_density()
    if dens is None:
        sys.exit("densité forêt indisponible.")
    forest = dens >= FOREST_MIN

    print(f"\n=== Validation spots {('('+a.label+')') if a.label else ''} — {len(spots)} coins ===")

    hab = habitat_grid()
    if hab is not None:
        rows, auc, n = auc_and_pct(hab, spots, forest)
        print(f"\nHABITAT (max SDM espèces) — référence : {n} mailles forêt")
        for name, v, pct in rows:
            s = "hors grille/forêt" if v is None else f"habitat={v:.3f}  percentile={100*pct:4.1f}%"
            print(f"  {name:32s} {s}")
        if auc is not None:
            print(f"  → AUC habitat = {auc:.3f}  (0.5=hasard, 1=parfait)")

    # Radar du jour (habitat × pousse), si la météo récente est en cache.
    try:
        served = list(core.fruiting_models())
        grid, used, date = fl.radar(served, a.date, params=core._radar_species_params())
    except Exception as e:
        grid = None
        print(f"\n(radar indisponible : {e})")
    if grid is not None:
        rows, auc, n = auc_and_pct(grid, spots, forest)
        print(f"\nRADAR {date} (habitat × pousse) — {len(used)} espèces en saison")
        for name, v, pct in rows:
            s = "n/a" if v is None else f"score={v:.3f}  percentile={100*pct:4.1f}%"
            print(f"  {name:32s} {s}")
        if auc is not None:
            print(f"  → AUC radar = {auc:.3f}")
    print()


if __name__ == "__main__":
    main()
