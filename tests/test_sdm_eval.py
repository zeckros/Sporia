"""Métriques d'évaluation SDM : Boyce continu (fenêtre glissante) + CV répétée."""

from __future__ import annotations

import numpy as np

from sporia.domain.sdm_eval import boyce_index_continuous, repeated_cv_metrics


def test_continuous_boyce_perfect_separation():
    rng = np.random.default_rng(0)
    pres = np.clip(rng.normal(0.75, 0.12, 500), 0, 1)
    bg = np.clip(rng.normal(0.25, 0.12, 500), 0, 1)
    assert boyce_index_continuous(pres, bg) > 0.8


def test_continuous_boyce_no_separation():
    rng = np.random.default_rng(1)
    same = lambda: np.clip(rng.normal(0.5, 0.15, 500), 0, 1)  # noqa: E731
    val = boyce_index_continuous(same(), same())
    assert np.isnan(val) or abs(val) < 0.5


def test_continuous_boyce_empty_returns_nan():
    assert np.isnan(boyce_index_continuous(np.array([]), np.array([0.5])))


def _separable_dataset(n_groups=40, per_group=20, seed=0):
    rng = np.random.default_rng(seed)
    X, y, g = [], [], []
    for gi in range(n_groups):
        pos = gi % 2  # la moitié des blocs "présence", l'autre "fond"
        for _ in range(per_group):
            center = 0.7 if pos else 0.3
            X.append([rng.normal(center, 0.2), rng.normal(center, 0.2)])
            y.append(pos)
            g.append(gi)
    return np.array(X), np.array(y), np.array(g)


def test_repeated_cv_returns_three_finite_floats():
    X, y, g = _separable_dataset()
    auc, boyce, se = repeated_cv_metrics(X, y, g, repeats=6, n_estimators=60)
    assert np.isfinite(auc) and np.isfinite(boyce) and np.isfinite(se)
    assert auc > 0.7  # données clairement séparables


def test_repeated_cv_is_deterministic():
    X, y, g = _separable_dataset()
    a = repeated_cv_metrics(X, y, g, repeats=6, n_estimators=60)
    b = repeated_cv_metrics(X, y, g, repeats=6, n_estimators=60)
    assert a == b


def test_repeated_cv_se_shrinks_with_more_repeats():
    X, y, g = _separable_dataset(n_groups=60)
    _, _, se_few = repeated_cv_metrics(X, y, g, repeats=4, n_estimators=60)
    _, _, se_many = repeated_cv_metrics(X, y, g, repeats=40, n_estimators=60)
    assert se_many < se_few
