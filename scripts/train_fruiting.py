#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SDM TEMPOREL — proba de FRUCTIFICATION (« c'est bon MAINTENANT », point #4).

Là où train_sdm.py modélise l'HABITAT (statique), ce script ajoute le « quand » :
chaque observation GBIF DATÉE est jointe à la météo ANTÉCÉDENTE de sa date
(archive Open-Meteo / ERA5 : pluie, température, humidité du sol des ~21 j avant).
Le fond = pseudo-absences ESPACE-TEMPS (lieu ET date aléatoires en saison) → le
modèle apprend à distinguer « bon habitat + bonnes conditions récentes » du reste.

Features = habitat statique (forêt/sol/relief) + météo antécédente (pluie 7/14/21 j,
T° moy. 14 j, humidité du sol, jours depuis pluie, mois).

Usage : python scripts/train_fruiting.py "Boletus edulis" [--max-pres 250] [--n-bg 500]
Dépend de scikit-learn. Météo mise en cache (data/cache/wx_archive/) → re-runs rapides.
Limites : nb d'appels archive borné (cap --max-pres) ; biais GBIF non corrigé ici.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import champi_core as core                      # noqa: E402
from train_sdm import (load_layers, cell_rc, match_key, blocks, boyce_index,  # noqa: E402
                       GRID_H, GRID_W, BBOX, GBIF_OCC)

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
WX_DIR = Path("data/cache/wx_archive")
WX_DIR.mkdir(parents=True, exist_ok=True)

STATIC = ["forest_density", "ph", "clay", "sand", "silt", "altitude", "slope", "northness"]
TEMPORAL = ["rain7", "rain14", "rain21", "tmean14", "sm_mean", "days_since_rain"]
FEATURES = STATIC + TEMPORAL
WIN = 21  # jours de météo antécédente
MAX_PER_CELL = 6  # plafond d'occurrences par maille (amincissement anti-biais GBIF)


def species_months(latin):
    for m in core.MUSHROOMS:
        if m["latin"] == latin:
            return sorted(m["months"])
    sys.exit(f"Espèce absente de MUSHROOMS : {latin}")


def fetch_dated(taxon_key, months, max_n=20000, min_year=2005, max_unc=5000):
    """Occurrences FR datées, dont le mois est dans la saison de l'espèce."""
    rows, off = [], 0
    while off < max_n:
        j = requests.get(GBIF_OCC, params={
            "taxonKey": taxon_key, "country": "FR", "hasCoordinate": "true",
            "hasGeospatialIssue": "false", "limit": 300, "offset": off}, timeout=60).json()
        for o in j.get("results", []):
            la, lo = o.get("decimalLatitude"), o.get("decimalLongitude")
            unc = o.get("coordinateUncertaintyInMeters")
            ev = o.get("eventDate") or ""
            if la is None or lo is None or len(ev) < 10:
                continue
            try:
                d = dt.date.fromisoformat(ev[:10])
            except ValueError:
                continue
            if d.year < min_year or d.month not in months:
                continue
            if unc is not None and unc > max_unc:
                continue
            if BBOX[0] <= lo <= BBOX[1] and BBOX[2] <= la <= BBOX[3]:
                rows.append((lo, la, d.isoformat()))
        off += 300
        if j.get("endOfRecords"):
            break
        time.sleep(0.08)
    return rows


def antecedent_wx(lat, lon, date_str):
    """Météo des WIN jours précédant date_str → features, depuis l'archive ERA5
    (mise en cache disque). Renvoie un dict ou None."""
    key = hashlib.md5(f"{lat:.3f}_{lon:.3f}_{date_str}".encode()).hexdigest()[:16]
    fp = WX_DIR / f"{key}.json"
    if fp.exists():
        d = json.loads(fp.read_text())
    else:
        end = dt.date.fromisoformat(date_str)
        start = end - dt.timedelta(days=WIN)
        for attempt in range(4):
            try:
                r = requests.get(ARCHIVE, params={
                    "latitude": round(lat, 3), "longitude": round(lon, 3),
                    "start_date": start.isoformat(), "end_date": end.isoformat(),
                    "daily": "precipitation_sum,temperature_2m_mean,soil_moisture_0_to_7cm_mean",
                    "timezone": "UTC"}, timeout=40)
                if r.status_code == 429:
                    time.sleep(12 * (attempt + 1)); continue
                r.raise_for_status()
                d = r.json().get("daily", {})
                break
            except Exception:
                if attempt == 3:
                    return None
                time.sleep(4 * (attempt + 1))
        else:
            return None
        fp.write_text(json.dumps(d))
        time.sleep(0.2)

    pr = np.array([x if x is not None else np.nan for x in d.get("precipitation_sum", [])], float)
    tm = np.array([x if x is not None else np.nan for x in d.get("temperature_2m_mean", [])], float)
    sm = np.array([x if x is not None else np.nan for x in d.get("soil_moisture_0_to_7cm_mean", [])], float)
    if pr.size < WIN:
        return None
    dsr = WIN
    for k in range(len(pr) - 1, -1, -1):
        if np.isfinite(pr[k]) and pr[k] >= 8.0:
            dsr = (len(pr) - 1) - k
            break
    return {
        "rain7": float(np.nansum(pr[-7:])), "rain14": float(np.nansum(pr[-14:])),
        "rain21": float(np.nansum(pr)), "tmean14": float(np.nanmean(tm[-14:])),
        "sm_mean": float(np.nanmean(sm[-7:])), "days_since_rain": float(dsr),
    }


def sample_static(layers, lon, lat):
    r, c = cell_rc([lon], [lat])
    r, c = int(r[0]), int(c[0])
    if not (0 <= r < GRID_H and 0 <= c < GRID_W):
        return None
    vals = [float(layers[f][r, c]) for f in STATIC]
    if not np.isfinite(vals).all():
        return None
    return vals, r, c


def build_rows(layers, france, samples, kind):
    """samples = liste de (lon, lat, date) → (X, rows, cols) valides."""
    X, rs, cs = [], [], []
    n = len(samples)
    for i, (lo, la, ds) in enumerate(samples, 1):
        st = sample_static(layers, lo, la)
        if st is None or not france[st[1], st[2]]:
            continue
        wx = antecedent_wx(la, lo, ds)
        if wx is None:
            continue
        X.append(st[0] + [wx[k] for k in TEMPORAL])
        rs.append(st[1]); cs.append(st[2])
        if i % 50 == 0 or i == n:
            print(f"    {kind} : {i}/{n} ({100*i//n} %)", flush=True)
    return np.array(X, float), np.array(rs, int), np.array(cs, int)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("species")
    ap.add_argument("--max-pres", type=int, default=250, help="occurrences présence (borne les appels API)")
    ap.add_argument("--n-bg", type=int, default=500)
    ap.add_argument("--min-leaf", type=int, default=3, help="min_samples_leaf (régularisation ; ↑ pour espèces peu nombreuses)")
    ap.add_argument("--base-only", action="store_true", help="n'utiliser que les 8 variables de base (sans WorldClim/occupation) — anti sur-apprentissage")
    a = ap.parse_args()

    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import GroupKFold
        from sklearn.metrics import roc_auc_score
    except ImportError:
        sys.exit("scikit-learn requis : pip install scikit-learn")

    months = species_months(a.species)
    layers, all_feats = load_layers()
    # Enrichissement « habitat fiable » : on ajoute les couches bakées WorldClim
    # (clim_*) et occupation du sol (lc_*) aux variables statiques — corrige la
    # dominance lat/lon. On écarte host_* (NaN hors-forêt + logique par guilde).
    global STATIC, FEATURES
    extra = [] if a.base_only else [f for f in all_feats if f.startswith("clim_") or f.startswith("lc_")]
    STATIC = STATIC + extra
    FEATURES = STATIC + TEMPORAL
    if extra:
        print(f"  features statiques enrichies : +{len(extra)} (WorldClim/occupation) -> {len(STATIC)} statiques")
    elif a.base_only:
        print(f"  --base-only : {len(STATIC)} variables de base (sans WorldClim/occupation)")
    ref = core._grid_ref()
    france = core._france_mask(str(ref)) if ref is not None else np.ones((GRID_H, GRID_W), bool)
    rng = np.random.default_rng(0)

    print(f"GBIF présence datée (mois {months}) : « {a.species} »…")
    occ = fetch_dated(match_key(a.species), months)
    print(f"  {len(occ)} occurrences datées en saison")

    # Amincissement anti-biais (presence-only) : retire les doublons exacts maille+date
    # (mêmes observateurs / même jour / même endroit) PUIS plafonne à MAX_PER_CELL
    # observations par maille — réduit le sur-poids des lieux sur-observés (villes,
    # sentiers, forêts populaires) tout en gardant la diversité de DATES (clé pour un
    # SDM temporel). cf. biais d'échantillonnage GBIF.
    if occ:
        from collections import defaultdict
        rr0, cc0 = cell_rc([o[0] for o in occ], [o[1] for o in occ])
        bycell, dedup = defaultdict(list), set()
        for o, r0, c0 in zip(occ, rr0, cc0):
            k = (int(r0), int(c0), o[2])
            if k in dedup:
                continue
            dedup.add(k); bycell[(int(r0), int(c0))].append(o)
        thinned = []
        for lst in bycell.values():
            if len(lst) <= MAX_PER_CELL:
                thinned += lst
            else:
                thinned += [lst[i] for i in rng.choice(len(lst), MAX_PER_CELL, replace=False)]
        print(f"  amincissement anti-biais : {len(occ)} -> {len(thinned)} "
              f"({len(bycell)} mailles, max {MAX_PER_CELL}/maille)")
        occ = thinned

    if len(occ) < 40:
        sys.exit("Trop peu d'occurrences datées.")
    if len(occ) > a.max_pres:
        occ = [occ[i] for i in rng.choice(len(occ), a.max_pres, replace=False)]
    print(f"  météo antécédente (archive ERA5) sur {len(occ)} présences…")
    Xp, pr, pc = build_rows(layers, france, occ, "présence")
    print(f"  {len(Xp)} présences exploitables")

    # Fond espace-temps : lieu France au hasard + date aléatoire en saison
    yrs = [int(d[:4]) for *_, d in occ] or [2015]
    ymin, ymax = min(yrs), max(yrs)
    fr, fc = np.where(france)
    bg = []
    for _ in range(a.n_bg):
        k = rng.integers(len(fr))
        la = core.terrain_data.GRID_LAT0 - fr[k] * 0.01
        lo = core.terrain_data.GRID_LON0 + fc[k] * 0.01
        y = int(rng.integers(ymin, ymax + 1)); mo = int(rng.choice(months)); day = int(rng.integers(1, 28))
        bg.append((lo, la, dt.date(y, mo, day).isoformat()))
    print(f"  météo antécédente sur {len(bg)} points d'arrière-plan espace-temps…")
    Xb, br, bc = build_rows(layers, france, bg, "fond")
    print(f"  {len(Xb)} points de fond exploitables")

    X = np.vstack([Xp, Xb]); y = np.r_[np.ones(len(Xp)), np.zeros(len(Xb))]
    grp = blocks(np.r_[pr, br], np.r_[pc, bc])

    gkf = GroupKFold(n_splits=min(5, len(np.unique(grp))))
    aucs, boyces = [], []
    for tr, te in gkf.split(X, y, groups=grp):
        clf = RandomForestClassifier(n_estimators=300, min_samples_leaf=a.min_leaf, n_jobs=-1,
                                     class_weight="balanced_subsample", random_state=0).fit(X[tr], y[tr])
        p = clf.predict_proba(X[te])[:, 1]
        if len(np.unique(y[te])) == 2:
            aucs.append(roc_auc_score(y[te], p))
        boyces.append(boyce_index(p[y[te] == 1], p[y[te] == 0]))
    print(f"\nFRUCTIFICATION — validation spatiale :")
    print(f"  AUC   = {np.nanmean(aucs):.3f}   Boyce = {np.nanmean(boyces):.3f}")

    base = RandomForestClassifier(n_estimators=500, min_samples_leaf=a.min_leaf, n_jobs=-1,
                                  class_weight="balanced_subsample", random_state=0).fit(X, y)
    print("Importance des variables :")
    for f, imp in sorted(zip(FEATURES, base.feature_importances_), key=lambda x: -x[1]):
        tag = "  (météo)" if f in TEMPORAL else ""
        print(f"  {f:16s} {imp:.3f}{tag}")
    tw = sum(imp for f, imp in zip(FEATURES, base.feature_importances_) if f in TEMPORAL)
    print(f"  -> poids total des variables MÉTÉO récentes : {tw:.0%}")

    import pickle
    out = Path("data/cache") / f"fruiting_{a.species.replace(' ', '_')}.pkl"
    out.write_bytes(pickle.dumps({"model": base, "features": FEATURES}))
    print(f"\nModèle sauvegardé -> {out}")
    print("(scoring d'une carte « propice maintenant » = appliquer ce modèle aux "
          "rasters récents RR/T/SM une fois ~21 j accumulés dans le pipeline.)")


if __name__ == "__main__":
    main()
