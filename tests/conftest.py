"""Shared pytest fixtures. Synthetic data only — no dependency on the 5 GB data/ tree."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _chdir_repo_root(monkeypatch):
    """Legacy modules resolve paths relative to CWD; run every test from repo root."""
    monkeypatch.chdir(REPO_ROOT)


@pytest.fixture
def weather_stub() -> dict:
    """A favourable-conditions weather dict, shaped like analyze_point_weather() output."""
    return {
        "month": 9,
        "temp_mean": 18.0,
        "soil_temp": 16.0,
        "days_since_rain": 8,
        "rain14": 30.0,
        "soil_moisture": 0.30,
    }


@pytest.fixture
def tiny_raster(tmp_path) -> Path:
    """A 4x4 EPSG:4326 GeoTIFF over a small area of France, for render/sample smoke tests."""
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_bounds

    w = h = 4
    west, south, east, north = 2.0, 46.0, 3.0, 47.0
    data = np.linspace(0, 20, w * h, dtype="float32").reshape(h, w)
    path = tmp_path / "T_20260901.tif"
    transform = from_bounds(west, south, east, north, w, h)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=h,
        width=w,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=np.nan,
    ) as dst:
        dst.write(data, 1)
    return path
