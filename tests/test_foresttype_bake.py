"""Agrégation forêt-type (classe CGLS → fraction par cellule)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from bake_foresttype_eu import CLASS_GROUPS, foresttype_fractions  # noqa: E402


def test_fractions_single_cell():
    # 6 pixels dans la cellule 0 : {2,4}=feuillu(2), {1,3}=conifère(2), {5}=mixte(1), 0=non-forêt(1)
    codes = np.array([2, 4, 1, 3, 5, 0])
    gidx = np.zeros(6, dtype=int)
    out = foresttype_fractions(codes, gidx, n_cells=2, groups=CLASS_GROUPS)
    assert out["fteu_broadleaf"][0] == 2 / 6
    assert out["fteu_needleleaf"][0] == 2 / 6
    assert out["fteu_mixed"][0] == 1 / 6
    # cellule 1 sans pixel → NaN
    assert np.isnan(out["fteu_broadleaf"][1])


def test_class_groups_partition_forest():
    # feuillu {2,4}, conifère {1,3}, mixte {5} — disjoints, couvrent les classes forêt
    assert CLASS_GROUPS["fteu_broadleaf"] == {2, 4}
    assert CLASS_GROUPS["fteu_needleleaf"] == {1, 3}
    assert CLASS_GROUPS["fteu_mixed"] == {5}
