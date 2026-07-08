"""Fiabilité de l'habitat depuis species_metrics.yaml — gating/paliers sur l'AUC."""

from __future__ import annotations

from sporia.domain.metrics import _tier_auc, confidence_tier, habitat_auc, is_reliable_habitat


def test_habitat_auc_loads_yaml():
    a = habitat_auc()
    assert isinstance(a, dict)
    assert "Boletus edulis" in a


def test_tier_auc_thresholds():
    assert _tier_auc(0.82) == "élevée"  # >= 0.80
    assert _tier_auc(0.75) == "bonne"  # >= 0.73, < 0.80
    assert _tier_auc(0.70) == "modérée"  # < 0.73


def test_reliable_when_auc_above_threshold():
    assert is_reliable_habitat("Boletus edulis") is True  # AUC 0.737 >= 0.65


def test_absent_species_unreliable_and_moderate():
    # Espèce absente du yaml → non servie ET palier « modérée ».
    assert is_reliable_habitat("Amanita muscaria") is False
    assert confidence_tier("Amanita muscaria") == "modérée"
