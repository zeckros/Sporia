"""Badge de confiance dérivé du Boyce habitat (chantier 4.5)."""

from sporia.domain import metrics


def test_tier_high():
    assert metrics.confidence_tier("Imleria badia") == "élevée"  # Boyce 0.727


def test_tier_good():
    assert metrics.confidence_tier("Boletus edulis") == "bonne"  # Boyce 0.389


def test_tier_moderate():
    assert metrics.confidence_tier("Agaricus campestris") == "modérée"  # Boyce 0.320


def test_tier_unknown_fallback_moderate():
    assert metrics.confidence_tier("Espèce inexistante") == "modérée"


def test_catalog_includes_confidence(monkeypatch):
    from sporia.web import app as webapp

    monkeypatch.setattr(webapp.core, "fruiting_models", lambda: ["Imleria badia"])
    catalog = webapp._catalog()
    assert catalog, "catalogue non vide attendu"
    assert catalog[0]["confidence"] == "élevée"
    assert "latin" in catalog[0] and "nom" in catalog[0] and "color" in catalog[0]
