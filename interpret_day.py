#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Interpretation script (adapted for collect_day.py output):
- lit data/daily/radar_cumul_YYYYMMDD.nc (produit par collect_day.py)
- lit data/cache/stations_YYYYMMDD.nc (stations)
- lit data/daily/arome_YYYYMMDD.csv (AROME interpolated points)
- applique règle hiérarchique station>radar>pa_arome
- construit grille France métropole en 0.01° (rés B)
- IDW interpolation (RR et T)
- écrit GeoTIFFs : output/tiff/RR_YYYY-MM-DD.tif and T_YYYY-MM-DD.tif
- fonctions utilitaires pour cumul/moyenne multi-jours
"""

import logging
from pathlib import Path
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone, date
from scipy.spatial import cKDTree
from scipy.interpolate import RegularGridInterpolator as RGI
import rasterio
from rasterio.transform import from_origin
import xarray as xr

DATA_DIR = Path("data/daily")
CACHE_DIR = Path("data/cache")
OUT_TIF_DIR = Path("output/tiff")
OUT_TIF_DIR.mkdir(parents=True, exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# France extent (lon_min, lon_max, lat_min, lat_max)
EXTENT = (-5.5, 10.5, 41.0, 51.5)
RES = 0.01  # ~1 km

def idw(points, values, xi, power=2.0, k=8, eps=1e-12):
    """IDW interpolation using cKDTree; points Nx2 (lon,lat)"""
    mask = np.isfinite(points).all(axis=1) & np.isfinite(values)
    pts = points[mask]
    vals = values[mask]
    if len(pts) == 0:
        return np.full(len(xi), np.nan)
    tree = cKDTree(pts)
    k_use = min(k, len(pts))
    dists, idx = tree.query(xi, k=k_use)
    if dists.ndim == 1:
        dists = dists[:, None]; idx = idx[:, None]
    weights = 1.0 / (dists**power + eps)
    vals_idx = vals[idx]
    num = np.sum(weights * vals_idx, axis=1)
    den = np.sum(weights, axis=1)
    res = num/den
    # where den ==0 set nan
    res[den == 0] = np.nan
    return res

def hierarchical_select(df):
    """
    Prend le dataframe stacké (timestamp, latitude, longitude, RR, T, source, priority)
    et pour each unique (latitude,longitude) keep the row with highest priority (largest priority value).
    """
    df2 = df.sort_values(["priority"], ascending=False)
    # round coordinates a bit to avoid float minor diffs (keep as-is if not wanted)
    df2["lat_r"] = df2["latitude"].round(5)
    df2["lon_r"] = df2["longitude"].round(5)
    df_unique = df2.drop_duplicates(subset=["lat_r","lon_r"], keep="first")
    return df_unique

def build_grid(extent=EXTENT, res=RES):
    lon_min, lon_max, lat_min, lat_max = extent
    xs = np.arange(lon_min, lon_max+res, res)
    ys = np.arange(lat_max, lat_min-res, -res)  # top -> bottom
    lonv, latv = np.meshgrid(xs, ys)
    points = np.vstack([lonv.ravel(), latv.ravel()]).T
    return lonv, latv, points

def write_geotiff(arr2d, xs, ys, out_fp, nodata=np.nan, crs="EPSG:4326"):
    """arr2d shape (ny, nx), xs,ys from build_grid (meshgrid)"""
    res_x = xs[0,1] - xs[0,0]
    res_y = ys[0,0] - ys[1,0] if ys.shape[0] > 1 else -res_x
    left = xs[0,0] - res_x/2.0
    top = ys[0,0] + res_y/2.0
    transform = from_origin(left, top, res_x, abs(res_y))
    # rasterio expects numpy array of (rows, cols)
    # convert NaN to nodata
    arr = np.array(arr2d, dtype=np.float32)
    # set nan -> nodata
    if np.isnan(nodata):
        # choose a nodata numeric value
        nodata_val = -9999.0
        arr[np.isnan(arr)] = nodata_val
    else:
        nodata_val = nodata
        arr[np.isnan(arr)] = nodata_val
    with rasterio.open(
        out_fp,
        "w",
        driver="GTiff",
        height=arr.shape[0],
        width=arr.shape[1],
        count=1,
        dtype=arr.dtype,
        crs=crs,
        transform=transform,
        nodata=nodata_val,
        compress="LZW"
    ) as dst:
        dst.write(arr, 1)

def interpret_day(day: date):
    """
    Fusion optimale par source :

    RR (précipitations) :
      1. Base AROME (IDW des points modèle)
      2. Radar rééchantillonné directement grille→grille (RegularGridInterpolator)
      3. Correction additive station-radar : biais = station - radar aux points stations,
         interpolé (IDW) sur toute la France et appliqué au champ radar
      4. Zones sans radar : IDW pur depuis stations

    T (température) :
      1. Base AROME (IDW des points modèle, intègre relief/topographie)
      2. Correction résiduelle : résidu = T_station - T_arome au même point,
         interpolé (IDW) et ajouté à la base AROME
      3. Sans AROME : IDW pur depuis stations
    """
    lonv, latv, grid_pts = build_grid()
    n = len(grid_pts)

    # ─── Chargement sources ──────────────────────────────────────────────────
    df_a, pts_a = None, None
    arome_file = DATA_DIR / f"arome_{day.strftime('%Y%m%d')}.csv"
    if arome_file.exists():
        try:
            df_a = pd.read_csv(arome_file).rename(columns={'lon': 'longitude', 'lat': 'latitude'})
            df_a = df_a.dropna(subset=['longitude', 'latitude'])
            pts_a = np.vstack([df_a['longitude'].values, df_a['latitude'].values]).T
            logging.info(f"AROME : {len(df_a)} points")
        except Exception as e:
            logging.warning(f"AROME load failed: {e}")
    else:
        logging.warning(f"AROME not found: {arome_file}")

    da_radar = None
    radar_file = DATA_DIR / f"radar_cumul_{day.strftime('%Y%m%d')}.nc"
    if radar_file.exists():
        try:
            da_radar = xr.open_dataarray(radar_file)
            logging.info(f"Radar : grille {da_radar.shape}")
        except Exception as e:
            logging.warning(f"Radar load failed: {e}")
    else:
        logging.warning(f"Radar not found: {radar_file}")

    df_s, pts_s = None, None
    stations_file = CACHE_DIR / f"stations_{day.strftime('%Y%m%d')}.nc"
    if stations_file.exists():
        try:
            df_s_raw = xr.open_dataset(stations_file).to_dataframe().reset_index()
            df_s_raw = df_s_raw.dropna(subset=['longitude', 'latitude'])
            # Aggregate per station: daily sum of rr1, daily mean of T.
            # The cache may hold multiple hours (via save_stations_to_netcdf accumulation)
            # or a single hour (legacy files without 'hour' column).
            rr_col = 'rr1' if 'rr1' in df_s_raw.columns else None
            t_col  = 't'   if 't'   in df_s_raw.columns else None
            agg_spec = {}
            if rr_col:
                agg_spec['RR'] = (rr_col, lambda x: pd.to_numeric(x, errors='coerce').sum(min_count=1))
            if t_col:
                agg_spec['T']  = (t_col,  lambda x: pd.to_numeric(x, errors='coerce').mean())
            if agg_spec:
                df_s = df_s_raw.groupby(['latitude', 'longitude'], as_index=False).agg(**agg_spec)
            else:
                df_s = df_s_raw[['latitude', 'longitude']].drop_duplicates().copy()
                df_s['RR'] = np.nan
                df_s['T']  = np.nan
            n_hours = df_s_raw['hour'].nunique() if 'hour' in df_s_raw.columns else 1
            pts_s = np.vstack([df_s['longitude'].values, df_s['latitude'].values]).T
            logging.info(f"Stations : {len(df_s)} stations ({n_hours} heures accumulées)")
        except Exception as e:
            logging.warning(f"Stations load failed: {e}")
    else:
        logging.warning(f"Stations not found: {stations_file}")

    if pts_a is None and da_radar is None and pts_s is None:
        raise ValueError(f"No data found for {day}")

    # ─── 1. AROME — couche de base (IDW) ────────────────────────────────────
    rr_arome_grid = np.full(n, np.nan, np.float32)
    t_arome_grid  = np.full(n, np.nan, np.float32)
    if pts_a is not None:
        rr_arome_grid = idw(pts_a, df_a['RR'].values.astype(float), grid_pts, power=2, k=8).astype(np.float32)
        t_arome_grid  = idw(pts_a, df_a['T'].values.astype(float),  grid_pts, power=2, k=8).astype(np.float32)

    # ─── 2. Radar — rééchantillonnage direct grille→grille ──────────────────
    rr_radar_grid = np.full(n, np.nan, np.float32)
    rgi_radar = None
    radar_lats = radar_lons = radar_vals_filled = None

    if da_radar is not None:
        try:
            lats_r = da_radar.latitude.values.copy()
            lons_r = da_radar.longitude.values.copy()
            vals_r = da_radar.values.astype(np.float32).copy()
            # Trie croissant pour RGI
            if lats_r[0] > lats_r[-1]:
                lats_r = lats_r[::-1]; vals_r = vals_r[::-1, :]
            if lons_r[0] > lons_r[-1]:
                lons_r = lons_r[::-1]; vals_r = vals_r[:, ::-1]
            radar_lats, radar_lons = lats_r, lons_r
            nan_mask_r = np.isnan(vals_r)
            radar_vals_filled = np.where(nan_mask_r, 0.0, vals_r)  # NaN → 0 (pas de pluie)
            rgi_radar = RGI((lats_r, lons_r), radar_vals_filled,
                            method='linear', bounds_error=False, fill_value=np.nan)
            rgi_nan   = RGI((lats_r, lons_r), nan_mask_r.astype(float),
                            method='linear', bounds_error=False, fill_value=1.0)
            pts_latlon = grid_pts[:, [1, 0]]          # (lon,lat) → (lat,lon)
            rr_radar_grid = rgi_radar(pts_latlon).astype(np.float32)
            nan_frac = rgi_nan(pts_latlon)
            rr_radar_grid[nan_frac > 0.5] = np.nan   # zone sans couverture radar
            logging.info(f"Radar rééchantillonné : {np.isfinite(rr_radar_grid).sum()} cellules valides")
        except Exception as e:
            logging.warning(f"Radar resampling failed: {e}")
            rgi_radar = None

    # ─── 3. Composition RR + correction biais stations ──────────────────────
    rr_final = rr_arome_grid.copy()
    radar_valid = np.isfinite(rr_radar_grid)
    rr_final[radar_valid] = rr_radar_grid[radar_valid]   # radar écrase AROME

    if pts_s is not None:
        rr_s = df_s['RR'].values.astype(float)

        if rgi_radar is not None:
            # Biais additif : station - radar à chaque station
            radar_at_s = rgi_radar(pts_s[:, [1, 0]]).astype(float)
            valid_bias = np.isfinite(rr_s) & np.isfinite(radar_at_s)
            if valid_bias.sum() >= 2:
                biases = rr_s[valid_bias] - radar_at_s[valid_bias]
                pts_bias = pts_s[valid_bias]
                # IQR outlier filter: reject stations with anomalous bias
                # (e.g. a single faulty station would otherwise corrupt the whole grid)
                if len(biases) >= 4:
                    q25, q75 = np.percentile(biases, 25), np.percentile(biases, 75)
                    iqr = q75 - q25
                    fence = max(3.0 * iqr, 5.0)
                    keep = np.abs(biases - np.median(biases)) <= fence
                    if keep.sum() >= 2:
                        n_removed = (~keep).sum()
                        if n_removed:
                            logging.info(f"Biais RR : {n_removed} station(s) outlier(s) écartée(s)")
                        pts_bias = pts_bias[keep]
                        biases   = biases[keep]
                bias_grid = idw(pts_bias, biases, grid_pts,
                                power=2, k=min(8, len(biases))).astype(np.float32)
                rr_final = np.clip(rr_final + bias_grid, 0.0, None)
                logging.info(
                    f"Biais station-radar : {len(biases)} stations, "
                    f"biais moyen={biases.mean():.2f} mm"
                )

        # Zones sans radar → IDW pur depuis stations
        no_radar = ~np.isfinite(rr_radar_grid)
        if no_radar.any():
            rr_stat_grid = idw(pts_s, rr_s, grid_pts, power=2, k=8).astype(np.float32)
            rr_final[no_radar] = rr_stat_grid[no_radar]

    # ─── 4. Composition T + correction résiduelle stations ──────────────────
    t_final = t_arome_grid.copy()

    if pts_s is not None:
        t_s = df_s['T'].values.astype(float)
        # Station T from Météo-France API is in Kelvin; AROME CSV is in Celsius.
        # Detect and convert to avoid a systematic +273 K residual error.
        t_s_finite = t_s[np.isfinite(t_s)]
        if len(t_s_finite) > 0 and np.median(t_s_finite) > 100:
            t_s = t_s - 273.15
            logging.info("Station T converted from Kelvin to Celsius (median was >100)")
        if pts_a is not None:
            # Résidu T : station - AROME au même point (voisin le plus proche)
            tree_a = cKDTree(pts_a)
            _, idx_a = tree_a.query(pts_s, k=1)
            t_arome_at_s = df_a['T'].values.astype(float)[idx_a]
            valid_t = np.isfinite(t_s) & np.isfinite(t_arome_at_s)
            if valid_t.sum() >= 2:
                residuals = t_s[valid_t] - t_arome_at_s[valid_t]
                res_grid = idw(pts_s[valid_t], residuals, grid_pts,
                               power=2, k=min(8, int(valid_t.sum()))).astype(np.float32)
                t_final = t_arome_grid + res_grid
                logging.info(
                    f"Résidus T : {valid_t.sum()} stations, "
                    f"résidu moyen={residuals.mean():.2f} K"
                )
        else:
            # Pas d'AROME : IDW pur depuis stations
            t_final = idw(pts_s, t_s, grid_pts, power=2, k=8).astype(np.float32)

    logging.info(
        f"Grille finale — RR valide: {np.isfinite(rr_final).sum()}, "
        f"T valide: {np.isfinite(t_final).sum()}"
    )

    rr_r = rr_final.reshape(lonv.shape)
    t_r  = t_final.reshape(lonv.shape)
    
    # ===== Write GeoTIFFs =====
    out_rr = OUT_TIF_DIR / f"RR_{day.strftime('%Y%m%d')}.tif"
    out_t = OUT_TIF_DIR / f"T_{day.strftime('%Y%m%d')}.tif"
    
    write_geotiff(rr_r, lonv, latv, out_rr)
    logging.info(f"Wrote RR: {out_rr}")
    
    write_geotiff(t_r, lonv, latv, out_t)
    logging.info(f"Wrote T: {out_t}")

    return out_rr, out_t

# --- multi-day helpers ---
def stack_days_and_compute(days, var="RR", agg="sum"):
    """
    days: list of datetime.date
    var: 'RR' or 'T'
    agg: 'sum' for RR, 'mean' for T
    Produces a stacked temporary raster as needed and writes a GeoTIFF aggregated.
    """
    logging.info(f"Processing {len(days)} days for {var} ({agg})...")
    
    # Produce intermediate rasters for each day and stack their arrays
    arrays = []
    for d in days:
        try:
            rr_fp, t_fp = interpret_day(d)
            if var == "RR":
                src = rr_fp
            else:
                src = t_fp
            with rasterio.open(src) as srcf:
                arrays.append(srcf.read(1).astype(np.float32))
        except Exception as e:
            logging.warning(f"Skipping {d}: {e}")
            continue
    
    if not arrays:
        raise RuntimeError("No arrays to stack")
    
    stacked = np.stack(arrays, axis=0)
    if agg == "sum":
        out_arr = np.nansum(stacked, axis=0)
    else:
        out_arr = np.nanmean(stacked, axis=0)
    
    # Write aggregated
    out_name = OUT_TIF_DIR / f"{var}_{days[0].strftime('%Y%m%d')}_to_{days[-1].strftime('%Y%m%d')}_{agg}.tif"
    
    # We need xs, ys to write. re-build
    lonv, latv, _ = build_grid()
    write_geotiff(out_arr, lonv, latv, out_name)
    logging.info(f"Wrote aggregate: {out_name}")
    return out_name

# --- CLI ---
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # Usage: python interpret_day.py YYYY-MM-DD
        # or: python interpret_day.py multi YYYY-MM-DD YYYY-MM-DD (range)
        if sys.argv[1] == "multi":
            if len(sys.argv) < 4:
                print("Usage: python interpret_day.py multi START_DATE END_DATE [var] [agg]")
                sys.exit(1)
            start_date = datetime.strptime(sys.argv[2], "%Y-%m-%d").date()
            end_date = datetime.strptime(sys.argv[3], "%Y-%m-%d").date()
            var = sys.argv[4] if len(sys.argv) > 4 else "RR"
            agg = sys.argv[5] if len(sys.argv) > 5 else ("sum" if var == "RR" else "mean")
            
            days = []
            current = start_date
            while current <= end_date:
                days.append(current)
                current += timedelta(days=1)
            
            stack_days_and_compute(days, var=var, agg=agg)
        else:
            day = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
            interpret_day(day)
    else:
        # Default: interpret today
        today = datetime.now(timezone.utc).date()
        logging.info(f"Processing today: {today}")
        interpret_day(today)
