#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
État du sol dynamique (humidité + température) — via Open-Meteo (gratuit, sans clé).

Open-Meteo expose, au pas horaire, l'humidité du sol (4 couches 0–27 cm) et la
température du sol (6 cm), issues d'un modèle ~11 km. On interroge une grille
grossière 0.25° sur la France (champ très lisse), on réduit chaque point à un
état journalier (moyenne des dernières 24 h valides), puis on IDW vers la grille
météo 0.01° pour écrire deux GeoTIFFs alignés sur RR_*.tif / T_*.tif :

  output/tiff/SM_YYYYMMDD.tif  — humidité racinaire 0–27 cm (m³/m³)
  output/tiff/TS_YYYYMMDD.tif  — température du sol à 6 cm (°C)

Réutilise build_grid / idw / write_geotiff de interpret_day. Appelé par
collect_day après interpret_day (cadencé ~1×/jour : le sol évolue lentement).
"""
from __future__ import annotations
import logging
import time
from datetime import date, datetime
from pathlib import Path

import numpy as np
import requests

from interpret_day import build_grid, idw, write_geotiff

OUT_TIF_DIR = Path("output/tiff")
DAILY_DIR = Path("data/daily")
OUT_TIF_DIR.mkdir(parents=True, exist_ok=True)
DAILY_DIR.mkdir(parents=True, exist_ok=True)

OM_URL = "https://api.open-meteo.com/v1/forecast"
# Grille de requête (grossière : l'humidité/température du sol varient peu).
OM_RES = 0.25
OM_EXTENT = (-5.5, 10.5, 41.0, 51.5)  # lon_min, lon_max, lat_min, lat_max
_BATCH = 70             # coordonnées par requête bulk (URL courte → moins de 502)
_MOIST_VARS = ["soil_moisture_0_1cm", "soil_moisture_1_3cm",
               "soil_moisture_3_9cm", "soil_moisture_9_27cm"]
_MOIST_WEIGHTS = np.array([1.0, 2.0, 6.0, 18.0])  # épaisseurs (cm) → moyenne 0–27 cm
_TEMP_VAR = "soil_temperature_6cm"


def _om_grid_points():
    lon_min, lon_max, lat_min, lat_max = OM_EXTENT
    lons = np.arange(lon_min, lon_max + OM_RES / 2, OM_RES)
    lats = np.arange(lat_min, lat_max + OM_RES / 2, OM_RES)
    lonv, latv = np.meshgrid(lons, lats)
    return np.column_stack([lonv.ravel(), latv.ravel()])  # (lon, lat)


def _last24_mean(series) -> float:
    vals = [x for x in series if x is not None]
    if not vals:
        return np.nan
    vals = vals[-24:]
    return float(np.mean(vals))


def _fetch_batch(pts_lonlat: np.ndarray) -> list[tuple[float, float, float, float]]:
    """Renvoie [(lon, lat, soil_moisture_0_27, soil_temp_6cm), …] pour un lot de
    points. Réduction = moyenne des 24 dernières heures valides."""
    lats = ",".join(f"{p[1]:.4f}" for p in pts_lonlat)
    lons = ",".join(f"{p[0]:.4f}" for p in pts_lonlat)
    params = {
        "latitude": lats, "longitude": lons,
        "hourly": ",".join(_MOIST_VARS + [_TEMP_VAR]),
        "past_days": 3, "forecast_days": 0,
        "timezone": "UTC", "cell_selection": "land",
    }
    for attempt in range(4):
        try:
            r = requests.get(OM_URL, params=params, timeout=60)
            if r.status_code == 429:
                time.sleep(8 * (attempt + 1))  # backoff sur quota
                continue
            r.raise_for_status()
            payload = r.json()
            break
        except Exception as e:
            if attempt == 3:
                logging.warning(f"[soil] batch failed: {e}")
                return []
            time.sleep(4 * (attempt + 1))
    else:
        return []

    locs = payload if isinstance(payload, list) else [payload]
    out = []
    for p, loc in zip(pts_lonlat, locs):
        h = loc.get("hourly", {}) if isinstance(loc, dict) else {}
        layers = [_last24_mean(h.get(v, [])) for v in _MOIST_VARS]
        if all(np.isnan(layers)):
            sm = np.nan
        else:
            w = np.where(np.isnan(layers), 0.0, _MOIST_WEIGHTS)
            vals = np.where(np.isnan(layers), 0.0, layers)
            sm = float((vals * w).sum() / w.sum()) if w.sum() > 0 else np.nan
        ts = _last24_mean(h.get(_TEMP_VAR, []))
        out.append((float(p[0]), float(p[1]), sm, ts))
    return out


def fetch_soil_grid() -> np.ndarray | None:
    """Interroge Open-Meteo sur la grille 0.25°. Renvoie un tableau Nx4
    (lon, lat, soil_moisture_0_27, soil_temp_6cm) ou None si tout échoue."""
    pts = _om_grid_points()
    rows = []
    n_batches = (len(pts) + _BATCH - 1) // _BATCH
    for i in range(0, len(pts), _BATCH):
        batch = pts[i:i + _BATCH]
        rows.extend(_fetch_batch(batch))
        logging.info(f"[soil] batch {i // _BATCH + 1}/{n_batches} "
                     f"({len(batch)} pts)")
        time.sleep(0.6)  # courtoisie / quota
    if not rows:
        return None
    arr = np.array(rows, dtype=np.float64)
    # garde les lignes avec au moins une mesure exploitable
    keep = ~(np.isnan(arr[:, 2]) & np.isnan(arr[:, 3]))
    return arr[keep] if keep.any() else None


def _needs_refresh(day: date, max_age_h: float = 18.0) -> bool:
    sm = OUT_TIF_DIR / f"SM_{day.strftime('%Y%m%d')}.tif"
    if not sm.exists():
        return True
    age_h = (time.time() - sm.stat().st_mtime) / 3600.0
    return age_h >= max_age_h


def produce_soil_rasters(day: date, force: bool = False):
    """Fetch Open-Meteo + IDW → écrit SM_*.tif et TS_*.tif sur la grille météo.
    Cadencé : ne refait rien si les rasters du jour ont < 18 h (sauf force)."""
    if not force and not _needs_refresh(day):
        logging.info(f"[soil] rasters {day} récents (<18 h) — fetch ignoré")
        return None

    data = fetch_soil_grid()
    if data is None:
        logging.warning("[soil] Open-Meteo injoignable — rasters sol non mis à jour")
        return None

    # cache des points bruts (debug / reprise)
    try:
        np.savetxt(DAILY_DIR / f"soil_{day.strftime('%Y%m%d')}.csv", data,
                   delimiter=",", header="lon,lat,soil_moisture,soil_temp",
                   comments="", fmt="%.5f")
    except Exception:
        pass

    lonv, latv, grid_pts = build_grid()
    src_pts = data[:, :2]
    sm = idw(src_pts, data[:, 2], grid_pts, power=2, k=8).reshape(lonv.shape)
    ts = idw(src_pts, data[:, 3], grid_pts, power=2, k=8).reshape(lonv.shape)

    out_sm = OUT_TIF_DIR / f"SM_{day.strftime('%Y%m%d')}.tif"
    out_ts = OUT_TIF_DIR / f"TS_{day.strftime('%Y%m%d')}.tif"
    write_geotiff(sm, lonv, latv, out_sm)
    write_geotiff(ts, lonv, latv, out_ts)
    logging.info(f"[soil] wrote {out_sm.name} (SM {np.nanmean(sm):.3f} m³/m³) "
                 f"+ {out_ts.name} (TS {np.nanmean(ts):.1f} °C) "
                 f"depuis {len(data)} points")
    return out_sm, out_ts


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    d = datetime.strptime(sys.argv[1], "%Y-%m-%d").date() if len(sys.argv) > 1 else date.today()
    produce_soil_rasters(d, force=True)
