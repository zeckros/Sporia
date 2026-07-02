"""Import + basic coverage for the overlays/ extraction from champi_core."""

from __future__ import annotations


def test_overlays_modules_import():
    import sporia.overlays.favorability  # noqa: F401
    import sporia.overlays.fruiting  # noqa: F401
    import sporia.overlays.radar  # noqa: F401
    import sporia.overlays.soil  # noqa: F401
    import sporia.overlays.terrain  # noqa: F401
    import sporia.overlays.weather  # noqa: F401


def test_fruiting_models_excludes_morille():
    from sporia.overlays.fruiting import fruiting_models

    served = fruiting_models()
    assert isinstance(served, list)
    assert "Morchella esculenta" not in served
