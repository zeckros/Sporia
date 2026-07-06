"""Métriques d'évaluation SDM : Boyce continu (fenêtre glissante) + CV répétée."""

from __future__ import annotations

import numpy as np

from sporia.domain.sdm_eval import boyce_index_continuous


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
