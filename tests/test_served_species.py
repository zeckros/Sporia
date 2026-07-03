"""Les espèces servies excluent les cartes d'habitat trompeuses (marqué slow : dépend
des modèles bakés data/cache/fruiting_*.pkl, absents en CI)."""

from __future__ import annotations

import pytest


@pytest.mark.slow
def test_served_excludes_misleading():
    from sporia.overlays.fruiting import fruiting_models

    served = fruiting_models()
    assert "Calocybe gambosa" not in served
    assert "Morchella esculenta" not in served


@pytest.mark.slow
def test_served_keeps_cepe_and_strong():
    from sporia.overlays.fruiting import fruiting_models

    served = fruiting_models()
    assert "Boletus edulis" in served  # 0.389, gardé (espèce vedette)
    assert "Imleria badia" in served  # 0.727
