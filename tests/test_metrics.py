"""Fiabilité de l'habitat depuis species_metrics.yaml."""

from __future__ import annotations

import pytest

from sporia.domain.metrics import (
    _conservative,
    _tier,
    confidence_tier,
    habitat_boyce,
    is_reliable_habitat,
)


def test_habitat_boyce_loads_yaml():
    b = habitat_boyce()
    assert isinstance(b, dict)
    assert "Boletus edulis" in b


def test_cepe_is_reliable():
    assert is_reliable_habitat("Boletus edulis") is True  # borne 0.672 - 0.026 >= 0.10


def test_mousseron_unreliable():
    assert is_reliable_habitat("Calocybe gambosa") is False  # borne -0.043 - 0.042 < 0.10


def test_absent_species_unreliable_and_moderate():
    # Espèce absente du yaml → _lower_bound None → non servie ET palier « modérée ».
    assert is_reliable_habitat("Amanita muscaria") is False
    assert confidence_tier("Amanita muscaria") == "modérée"


def test_conservative_bound():
    assert _conservative(0.50, 0.03) == pytest.approx(0.47)
    assert _conservative(0.12, 0.05) == pytest.approx(0.07)


def test_tier_thresholds_on_lower_bound():
    assert _tier(0.55) == "élevée"  # >= 0.50
    assert _tier(0.47) == "bonne"  # >= 0.35, < 0.50
    assert _tier(0.20) == "modérée"  # < 0.35
