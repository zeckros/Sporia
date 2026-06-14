#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bake des PROPRIÉTÉS DE SOL SUPPLÉMENTAIRES (axe P2.6) sur la grille Sporia.

On n'utilisait que texture (argile/sable/limon) + pH. On ajoute deux propriétés
SoilGrids directement pertinentes pour les champignons :

  • soc.npy  Carbone organique du sol (g/kg, topsoil 0–15 cm) — proxy de la matière
             organique / litière : nourriture des saprophytes et marqueur des sols
             forestiers riches et frais.
  • cec.npy  Capacité d'échange cationique (cmol(c)/kg) — fertilité / capacité du sol
             à retenir les nutriments, corrélée à la productivité du peuplement hôte.

Réutilise soil_data._wcs_property_depth (WCS ISRIC 250 m → grille 1601×1051). Sorties
hookées par train_sdm.py (cf. STATIC_FEATURES étendu).
Usage : python scripts/bake_soil_extra.py [--force]
"""
from __future__ import annotations
import argparse
import sys
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import soil_data                                # noqa: E402

CACHE = Path("data/cache")
# clé sortie → (propriété SoilGrids, facteur d'échelle vers unité « lisible »)
PROPS = {"soc": ("soc", 1 / 10.0),              # dg/kg → g/kg
         "cec": ("cec", 1 / 10.0)}              # mmol(c)/kg → cmol(c)/kg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    targets = {k: CACHE / f"{k}.npy" for k in PROPS}
    if not a.force and all(p.exists() for p in targets.values()):
        print("Couches sol supplémentaires déjà présentes (--force pour re-baker).")
        return

    for key, (prop, scale) in PROPS.items():
        layers = []
        for depth in soil_data.SOIL_DEPTHS:     # 0-5cm + 5-15cm = topsoil
            arr = soil_data._wcs_property_depth(prop, depth)
            if arr is not None:
                layers.append(arr)
            print(f"  {prop} {depth} {'OK' if arr is not None else 'ÉCHEC'}", flush=True)
        if not layers:
            print(f"  {prop} : WCS injoignable — on n'écrase pas un cache existant.")
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            grid = (np.nanmean(np.stack(layers), axis=0) * scale).astype(np.float32)
        np.save(targets[key], grid)
        v = grid[np.isfinite(grid)]
        print(f"  → {key}.npy  valid={v.size}  min={v.min():.1f} mean={v.mean():.1f} max={v.max():.1f}")
    print("\nFait. Ajoute soc/cec aux STATIC_FEATURES de train_sdm.py.")


if __name__ == "__main__":
    main()
