#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Le « quand » contient-il déjà le « où » ? — compare POUSSE seule / HABITAT seul / RADAR.

Sur les occurrences GBIF DATÉES EN SAISON (vrais événements de fructification, chacun à sa
date) vs un fond, on mesure AUC + indice de Boyce de trois scores, par espèce :
  • POUSSE   = proba du modèle de fructification (le « quand », avec son où implicite)
  • HABITAT  = SDM (le « où » dédié, prédicteurs riches : essence fine, TWI, sol…)
  • RADAR    = habitat × (HAB_FLOOR + (1-HAB_FLOOR)·pousse)   (ce qui est servi)

Si RADAR > POUSSE → le ×SDM ajoute une localisation que la pousse seule n'a pas (pas de
redondance). Si RADAR ≈ POUSSE → le « quand » contenait déjà le « où ».

Deux fonds :
  • défaut (cache-only)  : fond ESPACE-TEMPS (lieu+date aléatoires en saison), reproduit le
    jeu d'entraînement → retombe sur le cache météo (pas d'appel archive). Comparatif relatif.
  • --spatial            : fond = lieux forêt ALÉATOIRES à la MÊME date que chaque présence
    (timing ~constant → seule la localisation varie) → test spatial pur. Nécessite des appels
    archive Open-Meteo FRAIS (quota) ; à lancer au reset du quota.

Usage : python scripts/eval_radar.py            (cache-only, immédiat)
        python scripts/eval_radar.py --spatial  (test spatial pur ; fetch archive)
"""
from __future__ import annotations
import argparse
import datetime as dt
import os
import pickle
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import champi_core as core                            # noqa: E402
import mushroom_map as mmap                           # noqa: E402
import train_fruiting as tf                           # noqa: E402
from train_sdm import boyce_index                     # noqa: E402
from fruiting_live import HAB_FLOOR                    # noqa: E402

CACHE = Path("data/cache")
NOMS = {m["latin"]: m["nom"] for m in core.MUSHROOMS}


def _metrics(score_p, score_b):
    from sklearn.metrics import roc_auc_score
    y = np.r_[np.ones(len(score_p)), np.zeros(len(score_b))]
    s = np.r_[score_p, score_b]
    auc = roc_auc_score(y, s) if len(set(y.tolist())) == 2 else float("nan")
    return auc, boyce_index(np.clip(score_p, 0, 1), np.clip(score_b, 0, 1))


def _presence(sp, layers, france, max_pres, rng):
    """Présences datées en saison (réplique l'amincissement de train_fruiting.main)."""
    months = tf.species_months(sp)
    occ = tf.fetch_dated(tf.match_key(sp), months)
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
            thinned += lst if len(lst) <= tf.MAX_PER_CELL else \
                [lst[i] for i in rng.choice(len(lst), tf.MAX_PER_CELL, replace=False)]
        occ = thinned
    if len(occ) < 40:
        return None, months
    if len(occ) > max_pres:
        occ = [occ[i] for i in rng.choice(len(occ), max_pres, replace=False)]
    return occ, months


def eval_species(sp, layers, france, forest_cells, spatial, max_pres=500, n_bg=500, k=1):
    pkl = CACHE / f"fruiting_{sp.replace(' ', '_')}.pkl"
    sdmf = CACHE / f"sdm_{sp.replace(' ', '_')}.npy"
    if not pkl.exists() or not sdmf.exists():
        return None
    rng = np.random.default_rng(0)
    occ, months = _presence(sp, layers, france, max_pres, rng)
    if occ is None:
        return None
    Xp, pr, pc = tf.build_rows(layers, france, occ, "présence")
    if len(Xp) < 20:
        return None

    if spatial:
        # fond = lieux forêt aléatoires à la MÊME date que chaque présence (timing constant)
        fr, fc = forest_cells
        bg = []
        for (lo, la, d) in occ:
            for _ in range(k):
                j = rng.integers(len(fr))
                bg.append((core.terrain_data.GRID_LON0 + fc[j] * 0.01,
                           core.terrain_data.GRID_LAT0 - fr[j] * 0.01, d))
    else:
        # fond espace-temps (reproduit train_fruiting.main → cache)
        yrs = [int(d[:4]) for *_, d in occ] or [2015]
        ymin, ymax = min(yrs), max(yrs)
        fr, fc = np.where(france)
        bg = []
        for _ in range(n_bg):
            j = rng.integers(len(fr))
            y = int(rng.integers(ymin, ymax + 1)); mo = int(rng.choice(months)); day = int(rng.integers(1, 28))
            bg.append((core.terrain_data.GRID_LON0 + fc[j] * 0.01,
                       core.terrain_data.GRID_LAT0 - fr[j] * 0.01, dt.date(y, mo, day).isoformat()))
    Xb, br, bc = tf.build_rows(layers, france, bg, "fond")
    if len(Xb) < 20:
        return None

    obj = pickle.loads(pkl.read_bytes())
    model, feats = obj["model"], obj["features"]
    idx = [tf.FEATURES.index(f) for f in feats]
    pf_p = model.predict_proba(Xp[:, idx])[:, 1]
    pf_b = model.predict_proba(Xb[:, idx])[:, 1]
    sdm = np.load(sdmf)
    hab_p = np.nan_to_num(sdm[pr, pc]); hab_b = np.nan_to_num(sdm[br, bc])
    blend_p = hab_p * (HAB_FLOOR + (1 - HAB_FLOOR) * pf_p)
    blend_b = hab_b * (HAB_FLOOR + (1 - HAB_FLOOR) * pf_b)
    return {
        "pousse": _metrics(pf_p, pf_b),
        "habitat": _metrics(hab_p, hab_b),
        "radar": _metrics(blend_p, blend_b),
        "n": (len(Xp), len(Xb)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spatial", action="store_true",
                    help="fond = lieux forêt aléatoires à la même date (test spatial pur ; fetch archive frais)")
    ap.add_argument("--k", type=int, default=1, help="fond par présence en mode --spatial")
    a = ap.parse_args()
    # cache-only par défaut ; en --spatial on fetch frais (sinon les points aléatoires sont vides)
    if a.spatial:
        os.environ.pop("WX_CACHE_ONLY", None)
        print("Mode --spatial : fond lieux aléatoires même date — appels archive FRAIS (quota requis).")
    else:
        os.environ.setdefault("WX_CACHE_ONLY", "1")

    layers, all_feats = tf.load_layers()
    extra = [f for f in all_feats if f.startswith("clim_") or f.startswith("lc_")]
    tf.STATIC = tf.STATIC + extra
    tf.FEATURES = tf.STATIC + tf.TEMPORAL
    ref = core._grid_ref()
    france = core._france_mask(str(ref))
    dens = mmap.load_forest_density()
    forest_cells = np.where(dens >= 0.10) if dens is not None else np.where(france)

    excl = getattr(core, "EXCLUDED_FROM_MODELING", set())
    species = [m["latin"] for m in core.MUSHROOMS if m["latin"] not in excl]

    # On accumule (la progression de build_rows pollue stdout) puis on imprime le tableau À LA FIN.
    rows, agg = [], {"pousse": [], "habitat": [], "radar": []}
    for sp in species:
        r = eval_species(sp, layers, france, forest_cells, a.spatial, k=a.k)
        rows.append((NOMS.get(sp, sp), r))
        if r is not None:
            for key in agg:
                agg[key].append(r[key])

    head = (f"{'Espèce':24s} | {'AUC po':>6s} {'Boyce po':>8s} | {'AUC ha':>6s} {'Boyce ha':>8s}"
            f" | {'AUC ra':>6s} {'Boyce ra':>8s} | (n+/n-)")
    print("\n\n===================== COMPARATIF POUSSE / HABITAT / RADAR =====================")
    print(head)
    print("-" * len(head))
    for nom, r in rows:
        if r is None:
            print(f"{nom:24s} |  (insuffisant / cache manquant)")
            continue
        po, ha, ra = r["pousse"], r["habitat"], r["radar"]
        print(f"{nom:24s} | {po[0]:6.3f} {po[1]:8.3f} | {ha[0]:6.3f} {ha[1]:8.3f}"
              f" | {ra[0]:6.3f} {ra[1]:8.3f} | {r['n'][0]}/{r['n'][1]}")
    print("-" * len(head))
    if agg["radar"]:
        def m(key, i): return np.nanmean([x[i] for x in agg[key]])
        print(f"{'MOYENNE':24s} | {m('pousse',0):6.3f} {m('pousse',1):8.3f} | {m('habitat',0):6.3f} {m('habitat',1):8.3f}"
              f" | {m('radar',0):6.3f} {m('radar',1):8.3f}")
        print(f"\nPousse vs Radar : si Radar > Pousse, le ×SDM ajoute une localisation réelle "
              f"(pas de redondance).{' [fond espace-temps]' if not a.spatial else ' [spatial pur]'}")


if __name__ == "__main__":
    main()
