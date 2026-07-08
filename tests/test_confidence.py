"""Badge de confiance dérivé de l'AUC habitat."""

from sporia.domain import metrics


def test_tier_high():
    assert metrics.confidence_tier("Boletus aereus") == "élevée"  # AUC 0.832 >= 0.80


def test_tier_good():
    assert metrics.confidence_tier("Cantharellus cibarius") == "bonne"  # AUC 0.759 in [0.73,0.80)


def test_tier_moderate():
    assert metrics.confidence_tier("Calocybe gambosa") == "modérée"  # AUC 0.705 < 0.73


def test_tier_unknown_fallback_moderate():
    assert metrics.confidence_tier("Espèce inexistante") == "modérée"


def test_catalog_includes_confidence(monkeypatch):
    from sporia.web import app as webapp

    monkeypatch.setattr(webapp.core, "fruiting_models", lambda: ["Boletus aereus"])
    catalog = webapp._catalog()
    assert catalog, "catalogue non vide attendu"
    assert catalog[0]["confidence"] == "élevée"
    assert "latin" in catalog[0] and "nom" in catalog[0] and "color" in catalog[0]
