"""Les espèces servies suivent le gating d'habitat (AUC) — marqué slow : dépend des
modèles bakés data/cache/fruiting_*.pkl, absents en CI."""

from __future__ import annotations

import pytest


@pytest.mark.slow
def test_served_reflects_habitat_auc_gating():
    from sporia.overlays.fruiting import fruiting_models

    served = fruiting_models()
    # Calocybe : sauvée par le transfrontalier (AUC 0.705 >= seuil 0.65) → désormais servie.
    assert "Calocybe gambosa" in served
    # Morchella : pas de modèle de fructification baké → jamais servie ici.
    assert "Morchella esculenta" not in served


@pytest.mark.slow
def test_served_keeps_cepe_and_strong():
    from sporia.overlays.fruiting import fruiting_models

    served = fruiting_models()
    assert "Boletus edulis" in served  # AUC 0.737
    assert "Imleria badia" in served  # AUC 0.744
