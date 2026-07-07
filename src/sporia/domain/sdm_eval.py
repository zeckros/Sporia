"""Métriques d'évaluation du SDM d'habitat, pures et testables (utilisées par
scripts/train_sdm.py). Les dépendances lourdes (scipy, scikit-learn) sont importées
DANS les fonctions pour garder `import sporia` léger."""

from __future__ import annotations

import numpy as np


def boyce_index_continuous(pres, bg, window: float = 0.1, res: int = 100) -> float:
    """Indice de Boyce CONTINU (Hirzel 2006) : une fenêtre de largeur `window` (fraction
    de [0,1]) glisse sur `res` positions ; pour chacune, ratio P/E = (part des présences
    dans la fenêtre) / (part du fond dans la fenêtre) ; l'indice est la corrélation de
    Spearman entre le centre des fenêtres et le ratio, sur les fenêtres où le fond est
    présent. Moins sensible au découpage que la version à casiers fixes. nan si < 3
    fenêtres exploitables ou entrée vide."""
    from scipy.stats import spearmanr

    pres = np.asarray(pres, float)
    bg = np.asarray(bg, float)
    pres = pres[np.isfinite(pres)]
    bg = bg[np.isfinite(bg)]
    if len(pres) == 0 or len(bg) == 0:
        return float("nan")
    half = window / 2.0
    centers = np.linspace(half, 1.0 - half, res)
    mids, ratios = [], []
    for c in centers:
        lo, hi = c - half, c + half
        P = float(np.mean((pres >= lo) & (pres <= hi)))
        E = float(np.mean((bg >= lo) & (bg <= hi)))
        if E > 0:
            mids.append(c)
            ratios.append(P / E)
    if len(ratios) < 3:
        return float("nan")
    return float(spearmanr(mids, ratios).correlation)


def repeated_cv_metrics(
    X, y, groups, repeats: int = 25, k: int = 5, n_estimators: int = 200, seed: int = 0
) -> tuple[float, float, float]:
    """Métriques de CV spatiale STABILISÉES. Répète `repeats` fois : assigne
    aléatoirement chaque groupe (bloc spatial) à l'un des `k` folds ; par fold, entraîne
    un RandomForest et mesure AUC + Boyce continu ; moyenne sur les folds → un couple
    (auc, boyce) par répétition. Renvoie (auc_mean, boyce_mean, boyce_se) où
    boyce_se = std(boyce_par_répétition) / sqrt(nb de répétitions). Déterministe à `seed`
    fixe. NaN si aucune répétition exploitable."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import roc_auc_score

    X = np.asarray(X, float)
    y = np.asarray(y)
    groups = np.asarray(groups)
    uniq = np.unique(groups)
    aucs_rep, boyce_rep = [], []
    for rep in range(repeats):
        rng = np.random.default_rng(seed + rep)
        fold_of = {int(g): int(rng.integers(k)) for g in uniq}
        fold = np.array([fold_of[int(g)] for g in groups])
        aucs, boyces = [], []
        for f in range(k):
            te = fold == f
            tr = ~te
            if te.sum() == 0 or tr.sum() == 0 or len(np.unique(y[tr])) < 2:
                continue
            clf = RandomForestClassifier(
                n_estimators=n_estimators,
                min_samples_leaf=3,
                n_jobs=-1,
                class_weight="balanced_subsample",
                random_state=0,
            ).fit(X[tr], y[tr])
            p = clf.predict_proba(X[te])[:, 1]
            if len(np.unique(y[te])) == 2:
                aucs.append(roc_auc_score(y[te], p))
            boyces.append(boyce_index_continuous(p[y[te] == 1], p[y[te] == 0]))
        if aucs:
            aucs_rep.append(float(np.nanmean(aucs)))
        if boyces and np.isfinite(boyces).any():
            boyce_rep.append(float(np.nanmean(boyces)))
    auc_mean = float(np.nanmean(aucs_rep)) if aucs_rep else float("nan")
    boyce_mean = float(np.nanmean(boyce_rep)) if boyce_rep else float("nan")
    boyce_se = (
        float(np.nanstd(boyce_rep) / np.sqrt(len(boyce_rep)))
        if len(boyce_rep) > 1
        else float("nan")
    )
    return auc_mean, boyce_mean, boyce_se


def spatial_thin(rows, cols, max_n: int, block: int = 25, seed: int = 0):
    """Sous-échantillonne (rows, cols) à ≤ max_n cellules en préservant l'étalement spatial :
    regroupe les cellules par bloc de `block`×`block` (~0.25° à 0.01°) puis tire en round-robin
    entre blocs (chaque bloc mélangé). Renvoie (rows, cols) inchangés si len ≤ max_n."""
    from collections import defaultdict

    rows = np.asarray(rows)
    cols = np.asarray(cols)
    if len(rows) <= max_n:
        return rows, cols
    rng = np.random.default_rng(seed)
    buckets = defaultdict(list)
    for i, (r, c) in enumerate(zip(rows // block, cols // block, strict=False)):
        buckets[(int(r), int(c))].append(i)
    lists = [rng.permutation(v).tolist() for v in buckets.values()]
    order = []
    while len(order) < max_n and any(lists):
        for lst in lists:
            if lst:
                order.append(lst.pop())
                if len(order) >= max_n:
                    break
        lists = [lst for lst in lists if lst]
    idx = np.array(order[:max_n], int)
    return rows[idx], cols[idx]
