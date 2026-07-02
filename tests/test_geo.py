"""Regression coverage for the geo/ + places extraction from champi_core."""

from __future__ import annotations

import pytest


def test_hex_to_rgb():
    from sporia.geo.render import _hex_to_rgb

    assert _hex_to_rgb("#854d0e") == (133, 77, 14)


def test_tile_bbox_3857_covers_world_at_z0():
    from sporia.geo.rasters import _tile_bbox_3857

    w, s, e, n = _tile_bbox_3857(0, 0, 0)
    assert w < 0 < e and s < 0 < n


def test_geo_and_places_import():
    import sporia.geo.rasters  # noqa: F401
    import sporia.geo.render  # noqa: F401
    from sporia.places import (  # noqa: F401
        available_dates,
        find_commune_at,
        search_cities,
    )


@pytest.mark.slow
def test_sample_raster_reads(tiny_raster):
    from sporia.geo.rasters import sample_raster

    v = sample_raster(str(tiny_raster), 2.5, 46.5)
    assert v is None or isinstance(float(v), float)
