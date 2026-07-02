"""Rasters & géométrie — accès GeoTIFF, masques France/forêt, reprojections, grille de
référence, bbox de tuile. Extrait de champi_core (iso-comportement)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio import features
from rasterio.crs import CRS as RioCRS
from rasterio.warp import (
    Resampling as RioResampling,
)
from rasterio.warp import (
    calculate_default_transform,
)
from rasterio.warp import (
    reproject as rio_reproject,
)
from rasterio.warp import (
    transform_bounds as rio_transform_bounds,
)

from sporia.config import settings
from sporia.places import _static, available_dates

DATA_DIR = settings.output_tiff_dir
OVERLAY_DIR = settings.overlay_dir
MASK_CACHE = settings.data_cache_dir
_FOREST_MASK_NPZ = MASK_CACHE / "forest_mask.npz"
_WORLD_3857 = 20037508.342789244
_grid_ref_geo_cache: dict = {}
_forest_mask_cache = None
_forest_mask_tried = False


def sample_raster(raster_path, lon, lat):
    try:
        with rasterio.open(raster_path) as src:
            raw = list(src.sample([(lon, lat)]))[0][0]
            if src.nodata is not None and raw == src.nodata:
                return None
            return float(raw) if raw is not None and not np.isnan(raw) else None
    except Exception:
        return None


def _france_mask(raster_path: str):
    cache_file = MASK_CACHE / f"france_mask_{Path(raster_path).stem}.npy"
    if cache_file.exists():
        try:
            m = np.load(cache_file)
            if m.dtype == bool:
                return m
        except Exception:
            pass
    _, _, france_boundary, _ = _static()
    with rasterio.open(raster_path) as src:
        out_shape = (src.height, src.width)
        transform = src.transform
    mask_bool = features.rasterize(
        [(france_boundary, 1)],
        out_shape=out_shape,
        transform=transform,
        fill=0,
        default_value=1,
        dtype="uint8",
    ).astype(bool)
    try:
        np.save(cache_file, mask_bool)
    except Exception:
        pass
    return mask_bool


def _aggregate(dates, var):
    arrs = []
    for d in dates:
        f = DATA_DIR / (f"RR_{d}.tif" if var == "RR" else f"T_{d}.tif")
        if not f.exists():
            continue
        with rasterio.open(f) as src:
            a = src.read(1).astype(np.float32)
            if src.nodata is not None:
                a[a == src.nodata] = np.nan
            arrs.append(np.ma.masked_invalid(a))
    if not arrs:
        return None
    stacked = np.ma.stack(arrs)
    return stacked.sum(axis=0) if var == "RR" else stacked.mean(axis=0)


def _reproject_to_3857(arr_src, raster_path, resampling=RioResampling.bilinear):
    """Reprojette un tableau (grille du raster) en EPSG:3857 ; renvoie (arr, bounds_latlon).
    resampling=nearest pour les champs catégoriels (ex. classes de sol)."""
    with rasterio.open(raster_path) as src:
        src_crs = src.crs or RioCRS.from_epsg(4326)
        src_transform, src_w, src_h, src_bounds = src.transform, src.width, src.height, src.bounds
    left, bottom, right, top = src_bounds
    wm = RioCRS.from_epsg(3857)
    dtr, dw, dh = calculate_default_transform(src_crs, wm, src_w, src_h, *src_bounds)
    dst = np.full((dh, dw), np.nan, dtype=np.float32)
    rio_reproject(
        source=arr_src,
        destination=dst,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dtr,
        dst_crs=wm,
        resampling=resampling,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )
    el, et = dtr.c, dtr.f
    er, eb = el + dw * dtr.a, et + dh * dtr.e
    left, bottom, right, top = rio_transform_bounds(wm, RioCRS.from_epsg(4326), el, eb, er, et)
    return dst, {
        "left": float(left),
        "bottom": float(bottom),
        "right": float(right),
        "top": float(top),
    }


def _reproject_to_grid(arr_src, ref_path, west, south, east, north, W, H):
    """Reprojette la grille source sur une grille 3857 FIXE (bbox + dimensions données),
    en plus proche voisin. Sert à aligner le radar sur le masque forêt baké."""
    from rasterio.transform import from_bounds as _from_bounds

    with rasterio.open(ref_path) as src:
        src_crs = src.crs or RioCRS.from_epsg(4326)
        src_transform = src.transform
    dst = np.full((H, W), np.nan, dtype=np.float32)
    rio_reproject(
        source=np.ascontiguousarray(arr_src, dtype=np.float32),
        destination=dst,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=_from_bounds(west, south, east, north, W, H),
        dst_crs=RioCRS.from_epsg(3857),
        resampling=RioResampling.nearest,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )
    return dst


def _forest_mask():
    """(mask bool HxW, (west,south,east,north) 3857, bounds_latlon) ou None si non baké."""
    global _forest_mask_cache, _forest_mask_tried
    if _forest_mask_tried:
        return _forest_mask_cache
    _forest_mask_tried = True
    if not _FOREST_MASK_NPZ.exists():
        return None
    try:
        z = np.load(_FOREST_MASK_NPZ)
        H, W = int(z["shape"][0]), int(z["shape"][1])
        mask = np.unpackbits(z["packed"])[: H * W].reshape(H, W).astype(bool)
        west, south, east, north = (float(v) for v in z["bounds"])
        ll = rio_transform_bounds(
            RioCRS.from_epsg(3857), RioCRS.from_epsg(4326), west, south, east, north
        )
        bounds = {
            "left": float(ll[0]),
            "bottom": float(ll[1]),
            "right": float(ll[2]),
            "top": float(ll[3]),
        }
        _forest_mask_cache = (mask, (west, south, east, north), bounds)
    except Exception as e:
        print(f"[radar] masque forêt illisible : {e}", flush=True)
        _forest_mask_cache = None
    return _forest_mask_cache


def _grid_ref():
    """Raster de référence (géoréférencement de la grille) : n'importe quel RR/T."""
    dts = available_dates()
    if dts:
        cand = DATA_DIR / f"RR_{dts[-1].strftime('%Y%m%d')}.tif"
        if cand.exists():
            return cand
    tifs = sorted(DATA_DIR.glob("RR_*.tif")) or sorted(DATA_DIR.glob("T_*.tif"))
    return tifs[-1] if tifs else None


def _mask_to_france(grid2d, ref):
    """Met à NaN les cellules hors frontière France → l'overlay épouse les contours
    (et n'apparaît pas en rectangle sur la mer / les pays voisins)."""
    g = np.asarray(grid2d, np.float32).copy()
    try:
        mask = _france_mask(str(ref))
        if mask.shape == g.shape:
            g[~mask] = np.nan
    except Exception:
        pass
    return g


def _tile_bbox_3857(z, x, y):
    n = 2**z
    size = 2.0 * _WORLD_3857 / n
    west = -_WORLD_3857 + x * size
    north = _WORLD_3857 - y * size
    return west, north - size, west + size, north


def _grid_ref_geo(ref_path):
    """(crs, transform) du raster de référence, mis en cache (constants → on évite de
    rouvrir le GeoTIFF à chaque tuile)."""
    key = str(ref_path)
    if key not in _grid_ref_geo_cache:
        with rasterio.open(key) as src:
            _grid_ref_geo_cache[key] = (src.crs or RioCRS.from_epsg(4326), src.transform)
    return _grid_ref_geo_cache[key]
