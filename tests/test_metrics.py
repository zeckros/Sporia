"""Fiabilité de l'habitat depuis species_metrics.yaml."""

from __future__ import annotations

from sporia.domain.metrics import _conservative, _tier, habitat_boyce, is_reliable_habitat


def test_habitat_boyce_loads_yaml():
    b = habitat_boyce()
    assert isinstance(b, dict)
    assert "Boletus edulis" in b


def test_cepe_is_reliable():
    assert is_reliable_habitat("Boletus edulis") is True  # 0.389 >= 0.10


def test_mousseron_unreliable():
    assert is_reliable_habitat("Calocybe gambosa") is False  # -0.19 < 0.10


def test_species_without_model_unreliable():
    assert is_reliable_habitat("Morchella esculenta") is False  # absent du yaml


def test_conservative_bound():
    assert _conservative(0.50, 0.03) == 0.47
    assert _conservative(0.12, 0.05) == 0.07


def test_tier_thresholds_on_lower_bound():
    assert _tier(0.55) == "élevée"  # >= 0.50
    assert _tier(0.47) == "bonne"  # >= 0.35, < 0.50
    assert _tier(0.20) == "modérée"  # < 0.35
