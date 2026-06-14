#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Évalue le SCORE RADAR COMBINÉ (« où × quand ») par espèce.

Le radar n'est pas un modèle entraîné : c'est le produit habitat(SDM) × (HAB_FLOOR +
(1-HAB_FLOOR)·pousse). Ce script applique cette formule exacte aux occurrences GBIF
DATÉES (présence) vs un fond ESPACE-TEMPS, et en mesure AUC + indice de Boyce — la
discrimination réelle du radar tel que servi.

NB : in-sample (le modèle de fructification a vu ces points) → légèrement optimiste pour
la part « quand » ; la part « où » (SDM) vient d'un autre jeu. À lire comme indicatif,
à comparer aux colonnes habitat/fructification de report_metrics.

Météo via le cache (WX_CACHE_ONLY=1 conseillé). Usage : python scripts/eval_radar.py
"""
from __future__ import annotations
import os
import pickle
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("WX_CACHE_ONLY", "1")          # éval hors-ligne sur le cache météo
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import champi_core as core                            # noqa: E402
import train_fruiting as tf                           # noqa: E402
from train_sdm import blocks, boyce_index             # noqa: E402
from fruiting_live import HAB_FLOOR                    # noqa: E402

CACHE = Path("data/cache")
NOMS = {m["latin"]: m["nom"] for m in core.MUSHROOMS}


def eval_species(sp, layers, france, max_pres=500, n_bg=500):
    """Réplique EXACTEMENT la préparation de données de train_fruiting.main (même seed,
    amincissement, max_pres, n_bg) → les points retombent sur le cache météo du retrain."""
    import datetime as dt
    from collections import defaultdict
    from sklearn.metrics import roc_auc_score
    pkl = CACHE / f"fruiting_{sp.replace(' ', '_')}.pkl"
    sdmf = CACHE / f"sdm_{sp.replace(' ', '_')}.npy"
    if not pkl.exists() or not sdmf.exists():
        return None
    rng = np.random.default_rng(0)                     # comme train_fruiting (1 process/espèce)
    months = tf.species_months(sp)
    occ = tf.fetch_dated(tf.match_key(sp), months)
    # amincissement anti-biais (dédup maille+date puis cap MAX_PER_CELL) — identique à main
    if occ:
        rr0, cc0 = tf.cell_rc([o[0] for o in occ], [o[1] for o in occ])
        bycell, dedup = defaultdict(list), set()
        for o, r0, c0 in zip(occ, rr0, cc0):
            k = (int(r0), int(c0), o[2])
            if k in dedup:
                continue
            dedup.add(k); bycell[(int(r0), int(c0))].append(o)
        thinned = []
        for lst in bycell.values():
            if len(lst) <= tf.MAX_PER_CELL:
                thinned += lst
            else:
                thinned += [lst[i] for i in rng.choice(len(lst), tf.MAX_PER_CELL, replace=False)]
        occ = thinned
    if len(occ) < 40:
        return None
    if len(occ) > max_pres:
        occ = [occ[i] for i in rng.choice(len(occ), max_pres, replace=False)]
    Xp, pr, pc = tf.build_rows(layers, france, occ, "présence")
    # fond espace-temps (même ordre rng que main)
    yrs = [int(d[:4]) for *_, d in occ] or [2015]
    ymin, ymax = min(yrs), max(yrs)
    fr, fc = np.where(france)
    bg = []
    for _ in range(n_bg):
        k = rng.integers(len(fr))
        la = core.terrain_data.GRID_LAT0 - fr[k] * 0.01
        lo = core.terrain_data.GRID_LON0 + fc[k] * 0.01
        y = int(rng.integers(ymin, ymax + 1)); mo = int(rng.choice(months)); day = int(rng.integers(1, 28))
        bg.append((lo, la, dt.date(y, mo, day).isoformat()))
    Xb, br, bc = tf.build_rows(layers, france, bg, "fond")
    if len(Xp) < 20 or len(Xb) < 20:
        return None

    obj = pickle.loads(pkl.read_bytes())
    model, feats = obj["model"], obj["features"]
    idx = [tf.FEATURES.index(f) for f in feats]        # colonnes de build_rows → ordre du modèle
    pf_p = model.predict_proba(Xp[:, idx])[:, 1]
    pf_b = model.predict_proba(Xb[:, idx])[:, 1]
    sdm = np.load(sdmf)
    hab_p = np.nan_to_num(sdm[pr, pc]); hab_b = np.nan_to_num(sdm[br, bc])
    blend_p = hab_p * (HAB_FLOOR + (1 - HAB_FLOOR) * pf_p)
    blend_b = hab_b * (HAB_FLOOR + (1 - HAB_FLOOR) * pf_b)

    y = np.r_[np.ones(len(blend_p)), np.zeros(len(blend_b))]
    s = np.r_[blend_p, blend_b]
    auc = roc_auc_score(y, s)
    boyce = boyce_index(blend_p, blend_b)              # blend ∈ [0,1] → bins 0..1 OK
    return auc, boyce, len(Xp), len(Xb)


def main():
    layers, all_feats = tf.load_layers()
    extra = [f for f in all_feats if f.startswith("clim_") or f.startswith("lc_")]
    tf.STATIC = tf.STATIC + extra
    tf.FEATURES = tf.STATIC + tf.TEMPORAL
    ref = core._grid_ref()
    france = core._france_mask(str(ref))

    excl = getattr(core, "EXCLUDED_FROM_MODELING", set())
    species = [m["latin"] for m in core.MUSHROOMS if m["latin"] not in excl]
    print(f"{'Espèce':24s} | {'AUC radar':>9s} {'Boyce radar':>11s}  (n+/n-)")
    print("-" * 56)
    aucs, boyces = [], []
    for sp in species:
        r = eval_species(sp, layers, france)
        if r is None:
            print(f"{NOMS.get(sp, sp):24s} |   (insuffisant / cache manquant)")
            continue
        auc, boyce, npp, nbb = r
        aucs.append(auc); boyces.append(boyce)
        print(f"{NOMS.get(sp, sp):24s} | {auc:9.3f} {boyce:11.3f}  ({npp}/{nbb})")
    print("-" * 56)
    if aucs:
        print(f"{'MOYENNE':24s} | {np.mean(aucs):9.3f} {np.mean(boyces):11.3f}")


if __name__ == "__main__":
    main()
