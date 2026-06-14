#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bake de la DENSITÉ DE LISIÈRE (axe P2.8) sur la grille Sporia.

Beaucoup d'espèces (girolles, coulemelles, pieds bleus, lactaires…) fructifient
préférentiellement en LISIÈRE — l'écotone forêt/milieu ouvert, plus lumineux et
chaud. La densité de forêt seule ne distingue pas un cœur de massif d'une bordure.
On dérive donc, depuis la densité forestière 1 km déjà bakée (BD Forêt®) :

  • edge_density.npy : fraction de mailles « écotone » (bordure forêt + ourlet ouvert
    attenant) dans une fenêtre ~5 km. Élevée en mosaïque bocagère / lisières, faible
    en plein massif comme en plaine nue.

Sortie hookée par train_sdm.py (cf. STATIC_FEATURES étendu). Aucun réseau.
Usage : python scripts/bake_forest_edge.py [--force]
"""
from __future__ import annotations
import argparse
from pathlib import Path

import numpy as np

CACHE = Path("data/cache")
DENS = CACHE / "forest_density_1km.npy"
OUT = CACHE / "edge_density.npy"
GRID_H, GRID_W = 1051, 1601
FOREST_MIN = 0.30        # densité au-delà de laquelle on considère « forêt »


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if OUT.exists() and not a.force:
        print("edge_density.npy déjà présent (--force pour re-baker).")
        return
    if not DENS.exists():
        raise SystemExit("forest_density_1km.npy absent — bake la densité forêt d'abord "
                         "(mushroom_map.load_forest_density).")
    from scipy.ndimage import binary_erosion, binary_dilation, uniform_filter

    dens = np.load(DENS)
    forest = dens >= FOREST_MIN
    inner = binary_erosion(forest, iterations=1)
    forest_edge = forest & ~inner                       # mailles forêt en bordure
    open_fringe = binary_dilation(forest, iterations=1) & ~forest   # ourlet ouvert attenant
    ecotone = (forest_edge | open_fringe).astype(np.float32)
    edge_density = uniform_filter(ecotone, size=5, mode="nearest").astype(np.float32)

    np.save(OUT, edge_density)
    v = edge_density[np.isfinite(edge_density)]
    print(f"→ edge_density.npy  min={v.min():.3f} mean={v.mean():.3f} max={v.max():.3f}  "
          f"({100*(ecotone>0).mean():.1f} % mailles écotone)")
    print("Fait. Ajoute edge_density aux STATIC_FEATURES de train_sdm.py.")


if __name__ == "__main__":
    main()
