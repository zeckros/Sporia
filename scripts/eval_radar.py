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
from sporia import api as core                            # noqa: E402
from sporia.enrich import forest as mmap                           # noqa: E402
import train_fruiting as tf                           # noqa: E402
from train_sdm import boyce_index, LON0, LAT0         # noqa: E402
from sporia.enrich.fruiting_live import HAB_FLOOR                    # noqa: E402

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


def eval_species(sp, layers, france, forest_cells, mode, max_pres=500, n_bg=500, k=1, guard_days=21):
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

    if mode == "spatial":
        # fond = lieux forêt aléatoires à la MÊME date que chaque présence (timing constant)
        # → isole la skill SPATIALE (le « où »).
        fr, fc = forest_cells
        bg = []
        for (lo, la, d) in occ:
            for _ in range(k):
                j = rng.integers(len(fr))
                bg.append((LON0 + fc[j] * 0.01, LAT0 - fr[j] * 0.01, d))
    elif mode == "temporal":
        # fond = MÊME lieu que chaque présence, mais une autre date en saison (≥ guard j)
        # → isole la skill TEMPORELLE (le « quand ») : c'est le juge honnête de la pousse.
        yrs = [int(d[:4]) for *_, d in occ] or [2015]
        ymin, ymax = min(yrs), max(yrs)
        bg = []
        for (lo, la, ds) in occ:
            d0 = dt.date.fromisoformat(ds)
            for _ in range(k):
                dneg = d0
                for _try in range(20):
                    y = int(rng.integers(ymin, ymax + 1)); mo = int(rng.choice(months)); day = int(rng.integers(1, 28))
                    dneg = dt.date(y, mo, day)
                    if y != d0.year or abs((dneg - d0).days) >= guard_days:
                        break
                bg.append((lo, la, dneg.isoformat()))
    else:
        # fond espace-temps (reproduit train_fruiting.main → cache) : mélange où/quand, saturé.
        yrs = [int(d[:4]) for *_, d in occ] or [2015]
        ymin, ymax = min(yrs), max(yrs)
        fr, fc = np.where(france)
        bg = []
        for _ in range(n_bg):
            j = rng.integers(len(fr))
            y = int(rng.integers(ymin, ymax + 1)); mo = int(rng.choice(months)); day = int(rng.integers(1, 28))
            bg.append((LON0 + fc[j] * 0.01,
                       LAT0 - fr[j] * 0.01, dt.date(y, mo, day).isoformat()))
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


_METRICS_YAML = ROOT / "src" / "sporia" / "data" / "species_metrics.yaml"
# Ordre d'affichage stable des champs (habitat d'abord, puis pousse ré-validée, puis radar).
_FIELD_ORDER = ["boyce", "auc", "fruiting_boyce", "fruiting_auc", "radar_boyce", "radar_auc"]


def _fmt_entry(d: dict) -> str:
    keys = [k for k in _FIELD_ORDER if k in d] + [k for k in d if k not in _FIELD_ORDER]
    return "{" + ", ".join(f"{k}: {d[k]}" for k in keys) + "}"


def emit_yaml(by_latin: dict) -> Path:
    """Fusionne les métriques RÉ-VALIDÉES pousse (fruiting_*) + radar (radar_*) dans
    species_metrics.yaml, en PRÉSERVANT le boyce/auc HABITAT existant (produit par
    train_sdm/report_metrics et lu par is_reliable_habitat). Écrit un fichier trié par
    Boyce habitat décroissant."""
    import yaml
    raw = {}
    if _METRICS_YAML.exists():
        raw = yaml.safe_load(_METRICS_YAML.read_text(encoding="utf-8")) or {}
    def put(entry, key, val):
        if val is not None and np.isfinite(val):  # nan (Boyce sur bins dégénérés) → clé omise
            entry[key] = round(float(val), 3)
    for latin, r in by_latin.items():
        if r is None:
            continue
        entry = dict(raw.get(latin) or {})
        put(entry, "fruiting_auc", r["pousse"][0]); put(entry, "fruiting_boyce", r["pousse"][1])
        put(entry, "radar_auc", r["radar"][0]); put(entry, "radar_boyce", r["radar"][1])
        raw[latin] = entry
    hb = lambda v: v.get("boyce", -9.0) if isinstance(v, dict) else -9.0
    header = [
        "# Métriques par espèce — CV spatiale (Boyce ~0=hasard, 1=parfait).",
        "#   boyce/auc      = HABITAT (SDM)          — report_metrics.py --emit-yaml ; lu par is_reliable_habitat (seuil 0.10)",
        "#   fruiting_*     = FRUCTIFICATION seule    — eval_radar.py --emit-yaml (ré-validation)",
        "#   radar_*        = end-to-end habitat×pousse — eval_radar.py --emit-yaml (ce qui est réellement servi)",
    ]
    lines = header + [f"{latin}: {_fmt_entry(raw[latin])}" for latin in sorted(raw, key=lambda s: -hb(raw[s]))]
    _METRICS_YAML.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return _METRICS_YAML


def main():
    try:  # Windows : évite un crash cp1252 sur les caractères non-latin1 des messages
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--spatial", action="store_true",
                    help="fond = lieux forêt aléatoires à la même date (test SPATIAL pur ; fetch archive frais)")
    ap.add_argument("--temporal", action="store_true",
                    help="fond = même lieu, autre date en saison (test TEMPOREL pur = juge du « quand » ; fetch frais)")
    ap.add_argument("--k", type=int, default=1, help="fond par présence en mode --spatial/--temporal")
    ap.add_argument("--emit-yaml", action="store_true",
                    help="fusionne les métriques pousse+radar ré-validées dans species_metrics.yaml")
    ap.add_argument("--species", default=None,
                    help="restreint l'éval à ces espèces (noms latins séparés par des virgules) — borne le quota")
    a = ap.parse_args()
    only = {s.strip() for s in a.species.split(",")} if a.species else None
    mode = "spatial" if a.spatial else "temporal" if a.temporal else "spacetime"
    # cache-only pour le fond espace-temps (reproduit le cache) ; en spatial/temporal on fetch frais
    # (sinon les nouveaux couples lieu/date sont absents du cache).
    if mode == "spacetime":
        os.environ.setdefault("WX_CACHE_ONLY", "1")
    else:
        os.environ.pop("WX_CACHE_ONLY", None)
        print(f"Mode --{mode} : appels archive FRAIS (quota requis).")

    layers, all_feats = tf.load_layers()
    extra = [f for f in all_feats if f.startswith("clim_") or f.startswith("lc_")]
    tf.STATIC = tf.STATIC + extra
    tf.FEATURES = tf.STATIC + tf.TEMPORAL
    ref = core._grid_ref()
    france = core._france_mask(str(ref))
    dens = mmap.load_forest_density()
    forest_cells = np.where(dens >= 0.10) if dens is not None else np.where(france)

    excl = getattr(core, "EXCLUDED_FROM_MODELING", set())
    species = [m["latin"] for m in core.MUSHROOMS if m["latin"] not in excl and (only is None or m["latin"] in only)]

    # On accumule (la progression de build_rows pollue stdout) puis on imprime le tableau À LA FIN.
    rows, agg, by_latin = [], {"pousse": [], "habitat": [], "radar": []}, {}
    for sp in species:
        r = eval_species(sp, layers, france, forest_cells, mode, k=a.k)
        rows.append((NOMS.get(sp, sp), r))
        by_latin[sp] = r
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
              f"(pas de redondance). [fond {mode}]")

    if a.emit_yaml:
        p = emit_yaml(by_latin)
        n = sum(1 for r in by_latin.values() if r is not None)
        print(f"\n[emit] {p} — {n} espèces (fruiting_* + radar_*)")


if __name__ == "__main__":
    main()
