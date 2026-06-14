#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SDM — proba d'HABITAT d'une espèce de champignon (présence / arrière-plan).

V2 — intègre les améliorations qualité :
  • #1 ARRIÈRE-PLAN « TARGET-GROUP » : le fond est tiré d'autres occurrences
    fongiques GBIF (et non de points uniformes) → corrige le biais d'effort
    d'échantillonnage (villes/sentiers d'iNaturalist).
  • #2 VALIDATION SPATIALE PAR BLOCS + indice de BOYCE (au lieu d'un split
    aléatoire qui surestime à cause de l'autocorrélation spatiale).
  • #3 PRÉDICTEURS climat : latitude/longitude (proxys de gradient climatique &
    continentalité) + hook WorldClim (data/cache/clim_*.npy) si tu en déposes.
  • #5 CALIBRATION des probabilités (isotonic) pour que 0–1 ait un sens.

Réutilise les couches statiques déjà bakées par l'app (forêt, sol, relief).
Modèle « OÙ » (habitat) ; le « QUAND » (fructification météo) = train_fruiting.py.

Usage :
  python scripts/train_sdm.py "Cantharellus cibarius" [--bg target|random]
                              [--n-bg 8000] [--predict]
Dépend de scikit-learn + scipy.
"""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import champi_core as core          # noqa: E402
import mushroom_map as mmap         # noqa: E402
import soil_data                    # noqa: E402
import terrain_data                 # noqa: E402

GBIF_MATCH = "https://api.gbif.org/v1/species/match"
GBIF_OCC = "https://api.gbif.org/v1/occurrence/search"
FUNGI_KINGDOM_KEY = 5               # GBIF : règne Fungi (pour le target-group)

GRID_H, GRID_W, RES = 1051, 1601, 0.01
LON0, LAT0 = -5.5, 51.5
BBOX = (-5.5, 10.5, 41.0, 51.5)
BLOCK_DEG = 0.75                    # taille des blocs spatiaux de validation

# Couches statiques. Hook climat : tout fichier data/cache/clim_<nom>.npy aligné
# (1051×1601) est ajouté automatiquement (bake via scripts/bake_worldclim.py).
STATIC_FEATURES = ["forest_density", "ph", "clay", "sand", "silt",
                   "altitude", "slope", "northness"]
# Prédicteurs d'habitat supplémentaires (bakes dédiés), chargés par nom de fichier s'ils
# existent — valides partout (≠ host_*, qui est NaN hors-forêt et propre à la guilde) :
#   twi/tpi/dist_water/slope_dem (humidité topographique, bake_terrain_wetness.py),
#   soc/cec (matière organique & fertilité du sol, bake_soil_extra.py),
#   edge_density (lisières, bake_forest_edge.py).
EXTRA_STATIC = ["twi", "tpi", "dist_water", "slope_dem", "soc", "cec", "edge_density"]
# Proxys géographiques : utilisés UNIQUEMENT en l'absence de couches climat réelles
# (sinon lat/lon dominent et provoquent un sur-apprentissage spatial — cf. #3).
GEO_PROXY = ["lat", "lon"]

# Variables PAR GUILDE : l'arbre-hôte (host_*) ne sert qu'aux ectomycorhiziennes
# forestières. Pour les saprophytes (bois mort) et les espèces de prairie, l'essence
# forestière est hors-sujet et n'ajoute que du bruit (Pleurotus 0.43→0.13,
# Calocybe 0.22→−0.14 quand on la leur impose) → on la leur retire.
NO_HOST = {
    "Pleurotus ostreatus",     # saprophyte sur bois mort
    "Calocybe gambosa",        # prairie / lisière (mousseron de la Saint-Georges)
    "Agaricus campestris",     # prairie (rosé des prés)
    "Macrolepiota procera",    # prairie / lisière (coulemelle)
}


def species_feats(feats, species):
    """Sous-ensemble de variables propre à l'espèce (retire host_* si hors-guilde)."""
    drop_host = species in NO_HOST
    return [f for f in feats if not (drop_host and f.startswith("host_"))]


def load_layers():
    dens = mmap.load_forest_density()
    soil = soil_data.load_soil_static()
    terr = terrain_data.load_terrain_static()
    if dens is None or soil is None or terr is None:
        sys.exit("Couches manquantes — bake d'abord soil_data / terrain_data.")
    lonv = (LON0 + np.arange(GRID_W) * RES)[None, :].repeat(GRID_H, 0).astype(np.float32)
    latv = (LAT0 - np.arange(GRID_H) * RES)[:, None].repeat(GRID_W, 1).astype(np.float32)
    layers = {
        "forest_density": dens.astype(np.float32),
        "ph": soil["ph"], "clay": soil["clay"], "sand": soil["sand"], "silt": soil["silt"],
        "altitude": terr["altitude"], "slope": terr["slope"], "northness": terr["northness"],
        "lat": latv, "lon": lonv,
    }
    feats = list(STATIC_FEATURES)
    for name in EXTRA_STATIC:                                     # prédicteurs habitat dédiés
        p = Path("data/cache") / f"{name}.npy"
        try:
            if p.exists():
                arr = np.load(p)
                if arr.shape == (GRID_H, GRID_W):
                    layers[name] = arr.astype(np.float32)
                    feats.append(name)
                    print(f"  + couche habitat {name}")
        except Exception:
            pass
    clim = []
    for f in sorted(Path("data/cache").glob("clim_*.npy")):       # hook WorldClim/CHELSA
        try:
            arr = np.load(f)
            if arr.shape == (GRID_H, GRID_W):
                name = f.stem
                layers[name] = arr.astype(np.float32)
                clim.append(name)
                print(f"  + couche climat {name}")
        except Exception:
            pass
    if clim:
        feats += clim                                             # vrai climat → on lâche lat/lon
    else:
        feats += GEO_PROXY
        print("  (aucune couche clim_*.npy — repli sur les proxys lat/lon ; "
              "lance scripts/bake_worldclim.py pour le vrai climat)")
    for f in sorted(Path("data/cache").glob("lc_*.npy")):         # hook occupation du sol
        try:
            arr = np.load(f)
            if arr.shape == (GRID_H, GRID_W):
                layers[f.stem] = arr.astype(np.float32)
                feats.append(f.stem)
                print(f"  + couche occupation du sol {f.stem}")
        except Exception:
            pass
    for f in sorted(Path("data/cache").glob("host_*.npy")):       # hook arbre-hôte (feuillu/conifère)
        try:
            arr = np.load(f)
            if arr.shape == (GRID_H, GRID_W):
                layers[f.stem] = arr.astype(np.float32)
                feats.append(f.stem)
                print(f"  + couche arbre-hôte {f.stem}")
        except Exception:
            pass
    return layers, feats


def cell_rc(lon, lat):
    col = np.round((np.asarray(lon, float) - LON0) / RES).astype(int)
    row = np.round((LAT0 - np.asarray(lat, float)) / RES).astype(int)
    return row, col


def sample(layers, feats, row, col):
    inb = (row >= 0) & (row < GRID_H) & (col >= 0) & (col < GRID_W)
    r, c = np.clip(row, 0, GRID_H - 1), np.clip(col, 0, GRID_W - 1)
    X = np.full((len(row), len(feats)), np.nan, np.float32)
    for j, f in enumerate(feats):
        X[:, j] = layers[f][r, c]
    X[~inb] = np.nan
    return X


def match_key(name):
    k = requests.get(GBIF_MATCH, params={"name": name}, timeout=30).json().get("usageKey")
    if not k:
        sys.exit(f"Introuvable sur GBIF : {name}")
    return k


def fetch_occurrences(taxon_key, max_n=20000, min_year=2000, max_unc=5000, label=None):
    lons, lats, off, total = [], [], 0, None
    while off < max_n:
        j = requests.get(GBIF_OCC, params={
            "taxonKey": taxon_key, "country": "FR", "hasCoordinate": "true",
            "hasGeospatialIssue": "false", "limit": 300, "offset": off}, timeout=60).json()
        if total is None:
            total = min(j.get("count", max_n) or max_n, max_n)
        for o in j.get("results", []):
            la, lo = o.get("decimalLatitude"), o.get("decimalLongitude")
            yr, unc = o.get("year") or 0, o.get("coordinateUncertaintyInMeters")
            if la is None or lo is None or (yr and yr < min_year):
                continue
            if unc is not None and unc > max_unc:
                continue
            if BBOX[0] <= lo <= BBOX[1] and BBOX[2] <= la <= BBOX[3]:
                lons.append(lo); lats.append(la)
        off += 300
        if label and total and (off % 3000 == 0 or off >= total):
            pct = min(100, int(100 * off / max(total, 1)))
            print(f"    {label} : {min(off, total)}/{total} occ. ({pct} %)", flush=True)
        if j.get("endOfRecords"):
            break
        time.sleep(0.08)
    return np.array(lons), np.array(lats)


def unique_cells(row, col):
    seen, ri, ci = set(), [], []
    for r, c in zip(row, col):
        if (r, c) not in seen:
            seen.add((r, c)); ri.append(r); ci.append(c)
    return np.array(ri, int), np.array(ci, int)


def blocks(rows, cols):
    """Bloc spatial (groupe de validation) pour chaque cellule."""
    lat = LAT0 - rows * RES
    lon = LON0 + cols * RES
    return (((lat - BBOX[2]) // BLOCK_DEG).astype(int) * 1000
            + ((lon - BBOX[0]) // BLOCK_DEG).astype(int))


def boyce_index(pres, bg, nbins=10):
    """Indice de Boyce (presence-only) : corrélation de Spearman entre la
    suitabilité et le ratio P/E. ~1 = bon, ~0 = aléatoire."""
    from scipy.stats import spearmanr
    edges = np.linspace(0, 1, nbins + 1)
    mids, ratios = [], []
    for i in range(nbins):
        lo, hi = edges[i], edges[i + 1]
        P = np.mean((pres >= lo) & (pres < hi))
        E = np.mean((bg >= lo) & (bg < hi))
        if E > 0:
            mids.append((lo + hi) / 2); ratios.append(P / E)
    if len(ratios) < 3:
        return float("nan")
    return float(spearmanr(mids, ratios).correlation)


_BG_CACHE = Path("data/cache") / "sdm_bg_target_cells.npy"


def build_background(layers, feats, france, mode, n_bg):
    """Arrière-plan indépendant de l'espèce → (rows, cols, X). Récupéré 1 seule
    fois (mis en cache sur disque) et réutilisé pour toutes les espèces."""
    if mode == "target":
        if _BG_CACHE.exists():
            print("Arrière-plan target-group (cache disque)…")
            cells = np.load(_BG_CACHE)
            br0, bc0 = cells[0], cells[1]
        else:
            print("GBIF target-group (règne Fungi) — arrière-plan partagé…")
            br0, bc0 = unique_cells(*cell_rc(*fetch_occurrences(
                FUNGI_KINGDOM_KEY, max_n=60000, label="target-group")))
            np.save(_BG_CACHE, np.vstack([br0, bc0]))
    else:
        fr, fc = np.where(france)
        idx = np.random.default_rng(42).choice(len(fr), min(n_bg, len(fr)), replace=False)
        br0, bc0 = fr[idx], fc[idx]
    if len(br0) > n_bg:
        idx = np.random.default_rng(42).choice(len(br0), n_bg, replace=False)
        br0, bc0 = br0[idx], bc0[idx]
    Xb = sample(layers, feats, br0, bc0)
    # NB : host_* est NaN hors forêt (CGLS Forest-Type masqué). On NE filtre QUE sur
    # les variables toujours disponibles (base+climat+occupation) pour ne pas réduire
    # l'arrière-plan aux seules cellules forestières ; chaque espèce re-filtre ensuite
    # le fond sur SES variables (run_one) → fond correct par guilde.
    always = [i for i, f in enumerate(feats) if not f.startswith("host_")]
    ok = np.isfinite(Xb[:, always]).all(axis=1)
    print(f"  {ok.sum()} points d'arrière-plan ({mode})")
    return br0[ok], bc0[ok], Xb[ok]


def run_one(species, layers, feats, france, bg, predict, verbose=True):
    """Entraîne + valide (CV spatiale) + calibre l'habitat d'une espèce.
    Renvoie (n_presence, auc, boyce). Sauve un .npy si predict."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.model_selection import GroupKFold
    from sklearn.metrics import roc_auc_score

    sfeats = species_feats(feats, species)          # variables propres à la guilde
    idx = [feats.index(f) for f in sfeats]           # colonnes correspondantes dans l'arrière-plan
    pr, pc = unique_cells(*cell_rc(*fetch_occurrences(match_key(species))))
    Xp = sample(layers, sfeats, pr, pc)
    okp = np.isfinite(Xp).all(axis=1) & france[np.clip(pr, 0, GRID_H - 1), np.clip(pc, 0, GRID_W - 1)]
    pr, pc, Xp = pr[okp], pc[okp], Xp[okp]
    if len(pr) < 30:
        print(f"  [skip] {species} : seulement {len(pr)} occurrences")
        return len(pr), float("nan"), float("nan")

    br0, bc0, Xb = bg
    pres = set(zip(pr.tolist(), pc.tolist()))
    kb = np.array([(r, c) not in pres for r, c in zip(br0, bc0)])
    br0, bc0, Xb = br0[kb], bc0[kb], Xb[kb][:, idx]   # arrière-plan restreint aux mêmes variables
    okb = np.isfinite(Xb).all(axis=1)                 # puis aux lignes valides pour CES variables
    br0, bc0, Xb = br0[okb], bc0[okb], Xb[okb]

    X = np.vstack([Xp, Xb])
    y = np.r_[np.ones(len(Xp)), np.zeros(len(Xb))]
    grp = blocks(np.r_[pr, br0], np.r_[pc, bc0])

    gkf = GroupKFold(n_splits=min(5, len(np.unique(grp))))
    aucs, boyces = [], []
    for tr, te in gkf.split(X, y, groups=grp):
        clf = RandomForestClassifier(n_estimators=300, min_samples_leaf=3, n_jobs=-1,
                                     class_weight="balanced_subsample", random_state=0).fit(X[tr], y[tr])
        p = clf.predict_proba(X[te])[:, 1]
        if len(np.unique(y[te])) == 2:
            aucs.append(roc_auc_score(y[te], p))
        boyces.append(boyce_index(p[y[te] == 1], p[y[te] == 0]))
    auc, boyce = float(np.nanmean(aucs)), float(np.nanmean(boyces))

    base = RandomForestClassifier(n_estimators=500, min_samples_leaf=3, n_jobs=-1,
                                  class_weight="balanced_subsample", random_state=0).fit(X, y)
    if verbose:
        print(f"  présence={len(pr)}  AUC(spatial)={auc:.3f}  Boyce={boyce:.3f}")
        print("  importances : " + ", ".join(
            f"{f} {imp:.2f}" for f, imp in sorted(zip(sfeats, base.feature_importances_), key=lambda x: -x[1])[:5]))
    try:
        model = CalibratedClassifierCV(base, method="isotonic", cv=3).fit(X, y)
    except Exception:
        model = base   # repli si trop peu d'échantillons pour calibrer

    if predict:
        rows, cols = np.where(france)
        Xg = sample(layers, sfeats, rows, cols)
        ok = np.isfinite(Xg).all(axis=1)
        proba = np.full((GRID_H, GRID_W), np.nan, np.float32)
        proba[rows[ok], cols[ok]] = model.predict_proba(Xg[ok])[:, 1]
        out = Path("data/cache") / f"sdm_{species.replace(' ', '_')}.npy"
        np.save(out, proba)
        if verbose:
            print(f"  → {out.name}  (habitat moyen {np.nanmean(proba):.2f})")
    return len(pr), auc, boyce


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("species", nargs="?", help='nom latin, ou "ALL" / --all')
    ap.add_argument("--all", action="store_true", help="toutes les espèces de MUSHROOMS")
    ap.add_argument("--bg", choices=["target", "random"], default="target")
    ap.add_argument("--n-bg", type=int, default=8000)
    ap.add_argument("--predict", action="store_true")
    a = ap.parse_args()

    try:
        import sklearn  # noqa: F401
    except ImportError:
        sys.exit("scikit-learn requis : pip install scikit-learn")

    layers, feats = load_layers()
    ref = core._grid_ref()
    france = core._france_mask(str(ref)) if ref is not None else np.ones((GRID_H, GRID_W), bool)
    bg = build_background(layers, feats, france, a.bg, a.n_bg)

    do_all = a.all or (a.species or "").upper() == "ALL"
    if do_all:
        excl = getattr(core, "EXCLUDED_FROM_MODELING", set())
        species_list = [m["latin"] for m in core.MUSHROOMS if m["latin"] not in excl]
        if excl:
            print(f"(exclues de la modélisation : {', '.join(sorted(excl))})")
        print(f"\n=== Entraînement SDM sur {len(species_list)} espèces ===")
        summary = []
        for i, sp in enumerate(species_list, 1):
            print(f"\n• [{i}/{len(species_list)}] {sp}", flush=True)
            n, auc, boyce = run_one(sp, layers, feats, france, bg, a.predict)
            summary.append((sp, n, auc, boyce))
        print("\n===================== RÉCAPITULATIF =====================")
        print(f"{'espèce':32s} {'présence':>8s} {'AUC':>6s} {'Boyce':>6s}")
        for sp, n, auc, boyce in summary:
            print(f"{sp:32s} {n:8d} {auc:6.3f} {boyce:6.3f}")
    else:
        if not a.species:
            sys.exit('Indique une espèce, ou --all.')
        print(f"\n• {a.species}")
        run_one(a.species, layers, feats, france, bg, a.predict)


if __name__ == "__main__":
    main()
