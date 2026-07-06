"""Badge de confiance dérivé du Boyce habitat (chantier 4.5)."""

from sporia.domain import metrics


def test_tier_high():
    assert metrics.confidence_tier("Imleria badia") == "élevée"  # borne 0.645-0.034=0.611 >= 0.50


def test_tier_good():
    assert (
        metrics.confidence_tier("Boletus aereus") == "bonne"
    )  # borne 0.417-0.025=0.392 in [0.35,0.50)


def test_tier_moderate():
    assert (
        metrics.confidence_tier("Agaricus campestris") == "modérée"
    )  # borne 0.262-0.036=0.226 < 0.35


def test_tier_unknown_fallback_moderate():
    assert metrics.confidence_tier("Espèce inexistante") == "modérée"


def test_catalog_includes_confidence(monkeypatch):
    from sporia.web import app as webapp

    monkeypatch.setattr(webapp.core, "fruiting_models", lambda: ["Imleria badia"])
    catalog = webapp._catalog()
    assert catalog, "catalogue non vide attendu"
    assert catalog[0]["confidence"] == "élevée"
    assert "latin" in catalog[0] and "nom" in catalog[0] and "color" in catalog[0]
