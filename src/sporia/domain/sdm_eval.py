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
