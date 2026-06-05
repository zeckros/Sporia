#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Collecte incrémentale OPTIMISÉE :
- Toutes les 5 min: récupère dernier radar (cumul 5min)
- Toutes les heures: récupère stations
- Toutes les 6 heures: récupère AROME (24h complètes de données)
- Une fois par jour: cumul radar journalier

OPTIMISATIONS APPLIQUÉES:
1. Cache intelligent avec vérification d'existence
2. AROME 24h complet mais interpolation PARALLÉLISÉE (6 workers)
3. RegularGridInterpolator au lieu de griddata (10-100x plus rapide)
4. Cache NPZ pour résultats d'interpolation (instantané après 1ère fois)
5. Workers radar augmentés (4→8)
6. Traitement AROME uniquement toutes les 6h
7. Cache NetCDF pour stations
8. Meilleure gestion mémoire (float32, fermeture datasets)
"""

import os
import io
import re
import json
import time
import gzip
import tarfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
import requests
import h5py
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from scipy.interpolate import RegularGridInterpolator
import contextlib
import warnings
warnings.filterwarnings('ignore')
logging.getLogger('h5py').setLevel(logging.ERROR)
logging.getLogger('h5py._hl').setLevel(logging.ERROR)

# AROME est téléchargé en GeoTIFF (image/tiff) et lu avec rasterio.
# eccodes/cfgrib ne sont plus utilisés.

@contextlib.contextmanager
def _suppress_eccodes_stderr():
    """Supprime les messages C-level d'ecCodes (assertion failed sur Windows).
    contextlib.redirect_stderr ne fonctionne pas pour les sorties C natives ;
    on redirige directement le file descriptor 2 via os.dup2.
    """
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    old_fd = os.dup(2)
    os.dup2(devnull_fd, 2)
    try:
        yield
    finally:
        os.dup2(old_fd, 2)
        os.close(old_fd)
        os.close(devnull_fd)

# ==================== CONFIGURATION ====================
DATA_DIR = Path("data")
DAILY_DIR = DATA_DIR / "daily"
STATE_FILE = DATA_DIR / "state_fetch.json"
RADAR_DIR = DATA_DIR / "radar_h5"
AROME_DIR = DATA_DIR / "arome_wcs"
CACHE_DIR = DATA_DIR / "cache"

for d in [ DAILY_DIR, RADAR_DIR, AROME_DIR, CACHE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# API keys are loaded from environment variables. Do NOT commit secrets.
# For local development you can create a .env file and add it to .gitignore.

# URLs
RADAR_PACKET_URL = "https://public-api.meteofrance.fr/public/DPPaquetRadar/v1/mosaique/paquet"
PAQUET_URL = "https://public-api.meteofrance.fr/public/DPPaquetObs/v1/paquet/stations/horaire"
WCS_BASE_URL = "https://public-api.meteofrance.fr/public/arome/1.0/wcs/MF-NWP-HIGHRES-AROME-001-FRANCE-WCS"
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / '.env', override=True)
except Exception:
    pass

API_KEY_AROME = os.getenv('API_KEY_AROME')
API_KEY_STATIONS = os.getenv('API_KEY_STATIONS')
API_KEY_RADAR = os.getenv('API_KEY_RADAR')

if not API_KEY_AROME or not API_KEY_STATIONS or not API_KEY_RADAR:
    logging.warning('One or more API keys are not set in environment variables (API_KEY_AROME, API_KEY_STATIONS, API_KEY_RADAR).\n'
                    'Create a .env file or set the variables in your environment. See .env.example for format.')

TZ = timezone.utc
SOURCE_PRIORITY = {"station": 3, "radar": 2, "pa_arome": 1}

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ==================== GESTION ÉTAT ====================

def load_state():
    """Charge l'état de la dernière exécution"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.warning(f"Failed to load state file: {e}")
    return {}

def save_state(state):
    """Sauvegarde l'état"""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ==================== UTILITAIRES ====================

def extract_time_from_coverageid(cid: str) -> datetime:
    """Extrait le datetime d'un coverage ID AROME.
    Gère tous les suffixes _PT{N}H (ex: _PT1H, _PT6H, _PT12H, _PT24H).
    """
    part = cid.split("___")[1]
    m = re.match(r'^(.+?)_PT(\d+)H$', part)
    if m:
        t = datetime.strptime(m.group(1), "%Y-%m-%dT%H.%M.%SZ")
        return t + timedelta(hours=int(m.group(2)))
    return datetime.strptime(part, "%Y-%m-%dT%H.%M.%SZ")

# ==================== RADAR ====================

def _h5_name_from_archive(archive_name: str) -> str:
    """
    Convertit un nom de fichier d'archive en nom radar standardisé.
    Ex: 'T_LAME_D_EAU_METROPOLE_20251206204500.h5' → 'radar_20251206T204500Z.h5'
    Fallback : conserve le nom d'origine si aucun timestamp détecté.
    """
    m = re.search(r'(\d{8})(\d{6})', archive_name)
    if m:
        return f"radar_{m.group(1)}T{m.group(2)}Z.h5"
    return archive_name


def fetch_radar_packet():
    """
    Récupère le dernier paquet mosaïque radar via l'API DPPaquetRadar.
    Le paquet gzip contient les HDF5 des 3 derniers créneaux 5 min (15 min glissantes).
    Extrait et sauvegarde les fichiers HDF5 dans RADAR_DIR.
    Retourne la liste des Path sauvegardés.
    """
    headers = {"apikey": API_KEY_RADAR}
    try:
        resp = requests.get(RADAR_PACKET_URL, headers=headers, stream=True, timeout=60)
        if resp.status_code != 200:
            logging.warning(f"Radar packet: HTTP {resp.status_code}")
            return []
        content = resp.content
    except Exception as e:
        logging.warning(f"Radar packet fetch error: {e}")
        return []

    if not content:
        logging.warning("Radar packet: réponse vide")
        return []

    saved = []
    buf = io.BytesIO(content)

    # --- Essai 1 : archive tar.gz (plusieurs HDF5) ---
    buf.seek(0)
    try:
        with tarfile.open(fileobj=buf, mode='r:gz') as tar:
            for member in tar.getmembers():
                stem = Path(member.name).name
                if not (stem.endswith('.h5') or stem.endswith('.hdf5')):
                    continue
                f_obj = tar.extractfile(member)
                if f_obj is None:
                    continue
                out_path = RADAR_DIR / _h5_name_from_archive(stem)
                if not out_path.exists():
                    out_path.write_bytes(f_obj.read())
                    logging.info(f"Radar extrait (tar.gz): {out_path.name}")
                saved.append(out_path)
        if saved:
            return saved
    except Exception:
        pass

    # --- Essai 2 : gzip simple → un seul HDF5 ---
    buf.seek(0)
    try:
        with gzip.open(buf) as gz:
            data = gz.read()
        ts = datetime.now(TZ).replace(second=0, microsecond=0)
        ts_5min = ts.replace(minute=(ts.minute // 5) * 5)
        out_path = RADAR_DIR / f"radar_{ts_5min.strftime('%Y%m%dT%H%M%SZ')}.h5"
        if not out_path.exists():
            out_path.write_bytes(data)
            logging.info(f"Radar extrait (gzip simple): {out_path.name}")
        saved.append(out_path)
    except Exception as e:
        logging.warning(f"Impossible d'extraire le paquet radar: {e}")

    return saved

def load_radar_h5(path):
    """Charge un fichier radar HDF5 (format ODIM) et retourne un DataArray xarray.

    Applique le décodage ODIM complet :
      physical = raw * gain + offset
      nodata et undetect sont masqués → NaN
      filtre de cohérence : valeurs < 0 ou > 300 mm/h → NaN
    """
    import xarray as xr
    try:
        with h5py.File(path, "r") as f:
            data = f["dataset1/data1/data"][:]
            where = f.get("where")
            what  = f.get("dataset1/data1/what")

            if where is None:
                logging.error(f"Missing 'where' group in HDF5 file {path}")
                return None

            data = data.astype(np.float32)

            # --- Décodage ODIM gain / offset / nodata / undetect ---
            if what is not None:
                gain     = float(what.attrs.get("gain",     1.0))
                offset   = float(what.attrs.get("offset",   0.0))
                nodata   = what.attrs.get("nodata",   None)
                undetect = what.attrs.get("undetect", None)

                # Masque AVANT décodage (valeurs entières brutes)
                bad = np.zeros(data.shape, dtype=bool)
                if nodata   is not None: bad |= (data == float(nodata))
                if undetect is not None: bad |= (data == float(undetect))

                data = data * gain + offset
                data[bad] = np.nan

            # Filtre de cohérence physique (valeurs aberrantes résiduelles)
            data = np.where((data < 0) | (data > 300), np.nan, data)

            # --- Coordonnées géographiques ---
            if "lon_min" in where.attrs and "lon_max" in where.attrs:
                lon_min = float(where.attrs["lon_min"])
                lon_max = float(where.attrs["lon_max"])
                lat_min = float(where.attrs["lat_min"])
                lat_max = float(where.attrs["lat_max"])
            elif "LL_lon" in where.attrs:
                LL_lon = float(where.attrs["LL_lon"])
                LR_lon = float(where.attrs["LR_lon"])
                UL_lat = float(where.attrs["UL_lat"])
                LL_lat = float(where.attrs["LL_lat"])
                lon_min = min(LL_lon, float(where.attrs.get("UL_lon", LL_lon)))
                lon_max = max(LR_lon, float(where.attrs.get("UR_lon", LR_lon)))
                lat_min = min(LL_lat, float(where.attrs.get("LR_lat", LL_lat)))
                lat_max = UL_lat
            else:
                logging.error(f"Unknown coordinate system in {path}")
                return None

            ny, nx = data.shape
            lons = np.linspace(lon_min, lon_max, nx)
            lats = np.linspace(lat_max, lat_min, ny)
            return xr.DataArray(
                data,
                coords={"latitude": lats, "longitude": lons},
                dims=("latitude", "longitude"),
            )
    except Exception as e:
        logging.error(f"Failed to load radar file {path}: {e}")
        return None

def load_single_radar_file(fname):
    """Charge un fichier radar pour traitement parallèle"""
    try:
        # ✅ FIXED: load_radar_h5 returns DataArray only (or None)
        da = load_radar_h5(str(fname))
        
        if da is None:
            return None, None, None
            
        arr = da.values * (5.0 / 60.0)  # mm/h -> mm/5min
        return arr, da.latitude.values, da.longitude.values
    except Exception as e:
        logging.warning(f"Failed to load radar file {fname}: {e}")
        return None, None, None

def cumulative_radar_day_parallel(day, max_workers=8):
    """
    Calcule le cumul radar journalier en parallèle
    ✅ OPTIMISÉ: max_workers augmenté à 8
    """
    day_start = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=TZ)
    day_end = day_start + timedelta(days=1)
    
    files = []
    t = day_start
    while t < day_end:
        fname = RADAR_DIR / f"radar_{t.strftime('%Y%m%dT%H%M%SZ')}.h5"
        if fname.exists():
            files.append(fname)
        t += timedelta(minutes=5)
    
    if not files:
        logging.warning("No radar files found for cumulative daily")
        return None
    
    logging.info(f"Processing {len(files)} radar files for {day}")
    
    # ✅ Traitement parallèle avec 8 workers
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(load_single_radar_file, files))
    
    arrays = [r[0] for r in results if r[0] is not None]
    
    if not arrays:
        logging.warning("No valid radar data for cumulative daily")
        return None
    
    # Récupère les coordonnées du premier fichier valide
    latitudes, longitudes = None, None
    for r in results:
        if r[1] is not None and r[2] is not None:
            latitudes = r[1]
            longitudes = r[2]
            break
    
    if latitudes is None or longitudes is None:
        return None
    
    # ✅ Utilise dtype explicite pour éviter overflow
    cumul = np.nansum(arrays, axis=0, dtype=np.float32)
    
    import xarray as xr
    da_cumul = xr.DataArray(
        cumul,
        coords={"latitude": latitudes, "longitude": longitudes},
        dims=["latitude", "longitude"]
    )
    
    logging.info(f"Completed radar cumulative for {day}")
    return da_cumul

def save_daily_radar_cumul(day, da_cumul):
    """Sauvegarde le cumul radar journalier"""
    if da_cumul is None:
        logging.info(f"No radar cumulative data to save for {day}")
        return
    
    filename = DAILY_DIR / f"radar_cumul_{day.strftime('%Y%m%d')}.nc"
    da_cumul.to_netcdf(filename)
    logging.info(f"Saved daily radar cumulative to {filename}")

# ==================== STATIONS ====================

def fetch_paquet_hour(dt: datetime):
    """Récupère les données stations pour une heure via l'API."""
    iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {"date": iso, "format": "json"}
    headers = {"apikey": API_KEY_STATIONS, "accept": "application/json"}

    try:
        r = requests.get(PAQUET_URL, headers=headers, params=params, timeout=30)
        if r.status_code != 200:
            logging.warning(f"Paquet API returned {r.status_code} for {iso}")
            return pd.DataFrame()

        data = r.json()
        arr = data.get("data", data.get("observations", [])) if isinstance(data, dict) else data

        logging.info(f"Fetched stations data for {iso}")
        return paquet_json_to_df(arr)
    except Exception as e:
        logging.warning(f"Paquet fetch failed for {iso}: {e}")
        return pd.DataFrame()

def paquet_json_to_df(arr):
    """Convertit le JSON paquet en DataFrame"""
    rows = []
    for rec in arr:
        geo = rec.get("geo_id_insee") or rec.get("id_station") or rec.get("code")
        lat = rec.get("lat") if rec.get("lat") is not None else rec.get("latitude")
        lon = rec.get("lon") if rec.get("lon") is not None else rec.get("longitude")
        t = rec.get("t")
        rr1 = rec.get("rr1")
        rows.append({
            "geo_id_insee": geo,
            "latitude": lat,
            "longitude": lon,
            "t": t,
            "rr1": rr1
        })
    
    df = pd.DataFrame(rows)
    for c in ("latitude", "longitude", "t", "rr1"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def save_stations_to_netcdf(df, day):
    """
    Sauvegarde les stations en NetCDF et accumule toutes les heures du jour.
    Chaque appel ajoute l'heure courante sans écraser les heures précédentes,
    ce qui permet à interpret_day de calculer le cumul journalier réel (sum rr1).
    """
    filename = CACHE_DIR / f"stations_{day.strftime('%Y%m%d')}.nc"

    if df.empty:
        return

    try:
        import xarray as xr
        now_hour = datetime.now(TZ).replace(minute=0, second=0, microsecond=0)
        hour_str = now_hour.strftime('%Y%m%dT%H')

        df_new = df.drop_duplicates(subset=['latitude', 'longitude'], keep='first').copy()
        df_new['hour'] = hour_str

        # Accumulate: merge with existing records from previous hours of the same day
        if filename.exists():
            try:
                ds_existing = xr.open_dataset(filename)
                df_existing = ds_existing.to_dataframe().reset_index()
                ds_existing.close()
                if 'hour' in df_existing.columns:
                    # Remove the current hour (de-duplicate on re-run), then append
                    df_existing = df_existing[df_existing['hour'] != hour_str]
                    df_new = pd.concat(
                        [df_existing.drop(columns=['station_id'], errors='ignore'), df_new],
                        ignore_index=True
                    )
            except Exception as e:
                logging.warning(f"Could not read existing stations cache for merge: {e}")

        df_clean = df_new.drop_duplicates(subset=['latitude', 'longitude', 'hour'], keep='first')
        df_clean = df_clean.reset_index(drop=True)
        df_clean['station_id'] = range(len(df_clean))

        ds = df_clean.set_index('station_id').to_xarray()

        encoding = {}
        for col in ds.data_vars:
            var_dtype = ds[col].dtype
            if np.issubdtype(var_dtype, np.number):
                encoding[col] = {'zlib': True, 'complevel': 5}

        ds.to_netcdf(filename, encoding=encoding)
        n_hours = df_clean['hour'].nunique() if 'hour' in df_clean.columns else 1
        logging.info(f"Saved stations to {filename} ({len(df_clean)} records, {n_hours} hours)")
    except Exception as e:
        logging.warning(f"Failed to save stations NetCDF: {e}")

def load_stations_from_netcdf(day):
    """
    Charge les stations depuis le cache NetCDF
    ✅ NOUVEAU: Chargement rapide depuis cache
    """
    filename = CACHE_DIR / f"stations_{day.strftime('%Y%m%d')}.nc"
    
    if not filename.exists():
        return None
    
    try:
        import xarray as xr
        ds = xr.open_dataset(filename)
        df = ds.to_dataframe().reset_index()
        logging.info(f"Loaded stations from NetCDF cache for {day}")
        return df
    except Exception as e:
        logging.warning(f"Failed to load stations NetCDF: {e}")
        return None

# ==================== AROME ====================

def _last_arome_file_time() -> datetime:
    """Retourne le mtime du fichier GeoTIFF AROME le plus récent, ou None."""
    gribs = list(AROME_DIR.glob("*.tif"))
    if not gribs:
        return None
    latest = max(gribs, key=lambda f: f.stat().st_mtime)
    return datetime.fromtimestamp(latest.stat().st_mtime, tz=TZ)


def get_coverage_ids():
    """
    Récupère la liste des coverages AROME disponibles
    ✅ OPTIMISÉ: Timeout augmenté + retry + cache
    """
    # Cache des coverage IDs (valide 1 heure)
    cache_file = CACHE_DIR / "coverage_ids_cache.json"
    if cache_file.exists():
        try:
            cache_age = time.time() - cache_file.stat().st_mtime
            if cache_age < 3600:  # Cache valide 1h
                with open(cache_file, 'r') as f:
                    cached_ids = json.load(f)
                logging.info(f"Using cached coverage IDs ({len(cached_ids)} items)")
                return cached_ids
        except Exception:
            pass
    
    url = WCS_BASE_URL + "/GetCapabilities"
    headers = {"apikey": API_KEY_AROME, "accept": "*/*"}
    params = {"service": "WCS", "version": "2.0.1", "language": "fre"}
    
    # ✅ Retry avec timeout augmenté
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logging.info(f"Fetching AROME coverage IDs (attempt {attempt + 1}/{max_retries})...")
            r = requests.get(url, headers=headers, params=params, timeout=60)
            if r.status_code != 200:
                raise RuntimeError(f"Erreur GetCapabilities: {r.status_code}")
            
            import xml.etree.ElementTree as ET
            root = ET.fromstring(r.text)
            ns = {'wcs': 'http://www.opengis.net/wcs/2.0'}
            coverage_ids = [
                c.find('wcs:CoverageId', ns).text
                for c in root.findall('.//wcs:CoverageSummary', ns)
                if c.find('wcs:CoverageId', ns) is not None
            ]
            
            # ✅ Sauvegarde le cache uniquement si non vide
            if coverage_ids:
                with open(cache_file, 'w') as f:
                    json.dump(coverage_ids, f)

            logging.info(f"Fetched {len(coverage_ids)} coverage IDs")
            return coverage_ids
            
        except requests.exceptions.Timeout:
            logging.warning(f"Timeout on attempt {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                time.sleep(5)  # Attend 5s avant retry
            else:
                logging.error("Failed to get coverage IDs after all retries")
                return []
        except Exception as e:
            logging.error(f"Failed to get coverage IDs: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
            else:
                return []
    
    return []

def filter_coverages(coverage_ids, day):
    """Filtre les coverages pour un jour donné"""
    temp_sol = []
    precip = []

    for cid in coverage_ids:
        parts = cid.split("___")
        if len(parts) < 2:
            continue
        
        date_str = parts[-1]
        if "_PT" in date_str:
            date_str = date_str.split("_PT")[0]
        date_str = date_str.replace(".", ":").replace("Z", "")

        try:
            dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
            dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        # Garde uniquement les écheances PT1H
        pt_match = re.search(r'_PT(\d+)H', parts[-1])
        if pt_match and int(pt_match.group(1)) != 1:
            continue

        if dt.date() == day:
            if "TEMPERATURE__GROUND_OR_WATER_SURFACE" in cid and "BRIGHTNESS_TEMPERATURE" not in cid:
                temp_sol.append((dt, cid))
            elif "TOTAL_WATER_PRECIPITATION__GROUND_OR_WATER_SURFACE" in cid:
                precip.append((dt, cid))

    # Trie par datetime
    temp_sol.sort(key=lambda x: x[0])
    precip.sort(key=lambda x: x[0])
    
    return [x[1] for x in temp_sol], [x[1] for x in precip]

def download_coverage(coverage_id, bbox=None):
    # GeoTIFF : lu avec rasterio, aucune dépendance eccodes
    filename = f"{coverage_id}.tif"
    filepath = AROME_DIR / filename

    if filepath.exists() and filepath.stat().st_size > 2000:
        return filepath

    url = WCS_BASE_URL + "/GetCoverage"
    headers = {"apikey": API_KEY_AROME}

    encoded_time = extract_time_from_coverageid(coverage_id).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    ).replace(":", "%3A")

    params = {
        "service": "WCS",
        "version": "2.0.1",
        "request": "GetCoverage",
        "coverageId": coverage_id,
        "subset": [f"time({encoded_time})"],
        "format": "image/tiff"
    }

    if bbox:
        params["subset"].append(f"long({bbox[0]},{bbox[1]})")
        params["subset"].append(f"lat({bbox[2]},{bbox[3]})")

    try:
        r = requests.get(url, headers=headers, params=params, stream=True, timeout=60)
        if r.status_code != 200:
            logging.warning(f"Download {filename}: HTTP {r.status_code}")
            return None

        with open(filepath, "wb") as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)

        if filepath.stat().st_size < 2000:
            filepath.unlink()
            return None

        return filepath

    except Exception as e:
        logging.error(f"Download failed {filename}: {e}")
        if filepath.exists():
            filepath.unlink()
        return None


def download_arome_parallel(coverage_ids, day, bbox_france=(-5.5, 10.5, 41.0, 51.5), max_workers=4):
    """
    Télécharge plusieurs coverages AROME en parallèle
    ✅ OPTIMISÉ: Avec ThreadPoolExecutor
    """
    def download_one(cid):
        datehour = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=TZ)
        return download_coverage( cid, bbox_france)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(download_one, coverage_ids))
    
    return [r for r in results if r is not None]

def sample_arome_at_points_optimized(arome_filepath, points_lonlat):
    """Lit un GeoTIFF AROME avec rasterio et interpole bilinéairement aux points demandés.

    Les GeoTIFF du WCS AROME utilisent un CRS géographique en degrés (sphère GRIB),
    très proche de EPSG:4326 mais techniquement différent. On reprojette en WGS84 pour
    garantir la cohérence des coordonnées, quelle que soit la source du fichier.
    """
    import rasterio
    from rasterio.crs import CRS
    from rasterio.warp import reproject, calculate_default_transform, Resampling

    fpath = Path(arome_filepath)
    if not fpath.exists() or fpath.stat().st_size < 2000:
        return np.full(points_lonlat.shape[0], np.nan, dtype="float32")

    try:
        wgs84 = CRS.from_epsg(4326)

        with rasterio.open(fpath) as src:
            vals_src = src.read(1).astype(np.float32)
            nodata = src.nodata
            src_crs = src.crs
            src_transform = src.transform
            src_height, src_width = vals_src.shape

            # Masque nodata avant reprojection
            if nodata is not None:
                vals_src[vals_src == nodata] = np.nan

            # Reprojection en WGS84 si le CRS natif est différent (Lambert, LAEA, etc.)
            if src_crs is not None and src_crs != wgs84:
                dst_transform, dst_width, dst_height = calculate_default_transform(
                    src_crs, wgs84, src_width, src_height, *src.bounds
                )
                vals_dst = np.full((dst_height, dst_width), np.nan, dtype=np.float32)
                reproject(
                    source=vals_src,
                    destination=vals_dst,
                    src_transform=src_transform,
                    src_crs=src_crs,
                    dst_transform=dst_transform,
                    dst_crs=wgs84,
                    resampling=Resampling.bilinear,
                    src_nodata=np.nan,
                    dst_nodata=np.nan,
                )
                transform = dst_transform
                vals = vals_dst
                height, width = dst_height, dst_width
                logging.debug(f"Reprojected {fpath.name}: {src_crs.to_string()[:40]} → WGS84")
            else:
                transform = src_transform
                vals = vals_src
                height, width = src_height, src_width

        # Coordonnées WGS84 de la grille reprojectée
        cols = np.arange(width)
        rows = np.arange(height)
        xs = transform.c + (cols + 0.5) * transform.a   # longitudes
        ys = transform.f + (rows + 0.5) * transform.e   # latitudes (décroissant)

        # Tri croissant pour RegularGridInterpolator
        if ys[0] > ys[-1]:
            ys = ys[::-1]
            vals = vals[::-1, :]

        interp = RegularGridInterpolator(
            (ys, xs), vals,
            method="linear",
            bounds_error=False,
            fill_value=np.nan
        )
        pts = np.column_stack([points_lonlat[:, 1], points_lonlat[:, 0]])  # (lat, lon)
        return interp(pts).astype("float32")

    except Exception as e:
        logging.warning(f"sample_arome rasterio failed for {fpath.name}: {e}")
        return np.full(points_lonlat.shape[0], np.nan, dtype="float32")

def fetch_arome_for_day(day, points_lonlat, max_hours=24):
    """
    Récupère et interpole les données AROME pour un jour
    ✅ HYPER-OPTIMISÉ: 
    - Interpolation parallèle avec ProcessPoolExecutor
    - Cache des résultats d'interpolation
    - Limitation stricte du nombre de fichiers
    """
    # Vérifie le cache d'interpolation NPZ
    cache_file = CACHE_DIR / f"arome_interpolated_{day.strftime('%Y%m%d')}.npz"
    if cache_file.exists():
        # Invalidate cache if any AROME source GeoTIFF for this day was updated after the cache
        cache_mtime = cache_file.stat().st_mtime
        day_str_variants = (day.strftime('%Y-%m-%d'), day.strftime('%Y%m%d'))
        newer_sources = [
            f for f in AROME_DIR.glob("*.tif")
            if any(v in f.stem for v in day_str_variants) and f.stat().st_mtime > cache_mtime
        ]
        if newer_sources:
            logging.info(f"AROME source files updated — invalidating NPZ cache ({len(newer_sources)} newer files)")
            cache_file.unlink(missing_ok=True)
    if cache_file.exists():
        try:
            cached = np.load(cache_file)
            # Valide : mêmes points ET au moins quelques valeurs réelles
            if (np.array_equal(cached['points'], points_lonlat)
                    and np.isfinite(cached['temp']).sum() > 10):
                logging.info(f"Using cached AROME interpolation for {day}")
                ts = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=TZ)
                df = pd.DataFrame({
                    "timestamp": [ts] * len(cached['temp']),
                    "lat": points_lonlat[:, 1],
                    "lon": points_lonlat[:, 0],
                    "RR": cached['precip'],
                    "T": cached['temp'],
                    "source": ["pa_arome"] * len(cached['temp']),
                    "priority": [SOURCE_PRIORITY["pa_arome"]] * len(cached['temp'])
                })
                return df
            else:
                logging.info("NPZ cache invalide (NaN ou points différents) — re-fetch")
                cache_file.unlink(missing_ok=True)
        except Exception as e:
            logging.warning(f"Cache read failed: {e}")
            cache_file.unlink(missing_ok=True)
    
    coverage_ids = get_coverage_ids()
    if not coverage_ids:
        logging.warning("No AROME coverage IDs found")
        return pd.DataFrame()

    logging.info(f"[AROME DIAG] {len(coverage_ids)} coverage IDs au total")
    # Affiche les 3 premiers pour vérifier le format
    for cid in coverage_ids[:3]:
        logging.info(f"[AROME DIAG] exemple ID: {cid}")

    temp_ids, precip_ids = filter_coverages(coverage_ids, day)
    logging.info(f"[AROME DIAG] filtrés pour {day}: {len(temp_ids)} temp, {len(precip_ids)} precip")

    if not temp_ids and not precip_ids:
        # Affiche les dates disponibles pour aider au diagnostic
        dates_dispo = set()
        for cid in coverage_ids:
            parts = cid.split("___")
            if len(parts) >= 2:
                dates_dispo.add(parts[-1][:10])
        logging.warning(f"[AROME DIAG] Aucun ID pour {day}. Dates disponibles dans l'API: {sorted(dates_dispo)}")
        return pd.DataFrame()

    # Télécharge en parallèle
    download_arome_parallel(temp_ids + precip_ids, day)

    # Liste des fichiers GRIB disponibles pour ce jour
    tifs = list(AROME_DIR.glob("*.tif"))
    logging.info(f"[AROME DIAG] {len(tifs)} fichiers GeoTIFF total sur disque")

    # Filtre uniquement les fichiers du jour demandé ET valides
    gribs_filtered = []
    for f in tifs:
        if not (day.strftime('%Y%m%d') in f.stem or day.strftime('%Y-%m-%d') in f.stem):
            continue
        if f.stat().st_size < 2000:
            logging.warning(f"Skipping too small file: {f.name} (size={f.stat().st_size})")
            continue
        gribs_filtered.append(f)

    logging.info(f"[AROME DIAG] {len(gribs_filtered)} fichiers GeoTIFF pour {day}")

    # Nettoie les fichiers .idx
    for idx_file in AROME_DIR.glob("*.idx"):
        try:
            idx_file.unlink()
        except Exception:
            pass

    if not gribs_filtered:
        logging.warning(f"[AROME DIAG] Aucun fichier GRIB2 pour {day} — téléchargements échoués ?")
        return pd.DataFrame()
    
    logging.info(f"Interpolating {len(gribs_filtered)} AROME files...")
    
    # ✅ PARALLÉLISATION DE L'INTERPOLATION avec ThreadPoolExecutor
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    precip_vals = np.zeros(points_lonlat.shape[0], dtype=np.float32)
    temp_vals = []

    def interpolate_file(filepath):
        """Un GeoTIFF = une variable. Détecte temp/precip depuis le nom de fichier."""
        vals = sample_arome_at_points_optimized(str(filepath), points_lonlat)
        is_temp = "TEMPERATURE" in filepath.name
        return vals, is_temp

    with ThreadPoolExecutor(max_workers=6) as executor:
        future_to_file = {executor.submit(interpolate_file, f): f for f in gribs_filtered}

        for future in as_completed(future_to_file):
            try:
                vals, is_temp = future.result()
                if vals is None or np.isfinite(vals).sum() == 0:
                    continue
                if is_temp:
                    temp_vals.append(vals)
                else:
                    precip_vals += np.nan_to_num(vals, nan=0.0)
            except Exception as e:
                filepath = future_to_file[future]
                logging.warning(f"Failed to interpolate {filepath.name}: {e}")
    
    # Calcule température moyenne
    if temp_vals:
        temp_mean = np.nanmean(np.vstack(temp_vals), axis=0)
    else:
        temp_mean = np.full(points_lonlat.shape[0], np.nan)
    
    # ✅ Sauvegarde le cache d'interpolation
    try:
        np.savez_compressed(
            cache_file,
            points=points_lonlat,
            precip=precip_vals,
            temp=temp_mean
        )
        logging.info(f"Cached AROME interpolation to {cache_file}")
    except Exception as e:
        logging.warning(f"Failed to cache interpolation: {e}")
    
    ts = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=TZ)
    df = pd.DataFrame({
        "timestamp": [ts] * len(temp_mean),
        "lat": points_lonlat[:, 1],
        "lon": points_lonlat[:, 0],
        "RR": precip_vals,
        "T": temp_mean,
        "source": ["pa_arome"] * len(temp_mean),
        "priority": [SOURCE_PRIORITY["pa_arome"]] * len(temp_mean)
    })
    
    logging.info(f"AROME processing completed for {day}: {len(df)} points interpolated")
    return df

# ==================== MAIN OPTIMISÉ ====================

def main():
    """
    Fonction principale OPTIMISÉE
    
    ✅ OPTIMISATIONS:
    1. Radar 5min: toujours (léger)
    2. Stations: toutes les heures (léger)
    3. Cumul radar journalier: une fois par jour
    4. AROME: toutes les 6h SEULEMENT, limité à 6h de données
    """
    start_time = time.time()
    state = load_state()
    now = datetime.now(TZ)
    day = now.date()
    current_hour = now.hour
    
    logging.info("=" * 60)
    logging.info(f"STARTING OPTIMIZED COLLECTION FOR {now.isoformat()}")
    logging.info("=" * 60)
    
    # ==================== 1. RADAR PAQUET (toujours) ====================
    logging.info("\n[1/4] Fetching radar packet (DPPaquetRadar)...")
    radar_files = fetch_radar_packet()
    if radar_files:
        logging.info(f"✓ {len(radar_files)} fichier(s) radar extrait(s): {[f.name for f in radar_files]}")
    else:
        logging.warning("✗ Radar packet fetch failed")
    
    # ==================== 2. STATIONS (toutes les heures) ====================
    logging.info("\n[2/4] Fetching stations data...")
    hour_dt = now.replace(minute=0, second=0, microsecond=0)
    df_stations = fetch_paquet_hour(hour_dt)
    
    if not df_stations.empty:
        logging.info(f"✓ Fetched {len(df_stations)} stations")
        # Sauvegarde en cache NetCDF
        save_stations_to_netcdf(df_stations, day)
    else:
        logging.warning("✗ No stations data fetched")
    
    # ==================== 3. CUMUL RADAR JOURNALIER (une fois par jour) ====================
    logging.info("\n[3/4] Checking daily radar cumulative...")
    radar_cumul_file = DAILY_DIR / f"radar_cumul_{day.strftime('%Y%m%d')}.nc"
    need_cumul = (
        "last_cumul_day" not in state
        or state["last_cumul_day"] != str(day)
        or not radar_cumul_file.exists()   # re-calcule si le fichier manque
    )
    if need_cumul:
        logging.info("Computing daily radar cumulative...")
        da_cumul = cumulative_radar_day_parallel(day, max_workers=8)
        save_daily_radar_cumul(day, da_cumul)
        if da_cumul is not None:
            state["last_cumul_day"] = str(day)
            save_state(state)
            logging.info("✓ Daily radar cumulative completed")
        else:
            logging.warning("✗ Radar cumulative empty — will retry next run")
    else:
        logging.info(f"✓ Daily radar cumulative already computed for {day}")
    
    # ==================== 4. AROME (toutes les 6h, limité à 6h de données) ====================
    logging.info("\n[4/4] Checking AROME data...")
    
    # Fetch AROME si le CSV du jour n'existe pas ou s'il date de plus de 6h.
    # On regarde le CSV (sortie réelle) plutôt que les GRIB2, pour éviter de
    # confondre les fichiers d'un jour précédent encore présents sur disque.
    arome_csv_today = DAILY_DIR / f"arome_{day.strftime('%Y%m%d')}.csv"
    if not arome_csv_today.exists():
        should_fetch_arome = True
        logging.info(f"[AROME] CSV absent → fetch déclenché")
    else:
        csv_age_h = (now - datetime.fromtimestamp(arome_csv_today.stat().st_mtime, tz=TZ)).total_seconds() / 3600
        should_fetch_arome = csv_age_h >= 6
        logging.info(f"[AROME] CSV présent, âge={csv_age_h:.1f}h → fetch={'oui' if should_fetch_arome else 'non'}")

    if should_fetch_arome:
        logging.info("Fetching AROME (full 24 hours coverage)...")
        # Grille fixe régulière 0.1° sur la France métropolitaine (~17 000 points).
        # Indépendante des stations : AROME est toujours fetchée même si les stations
        # sont indisponibles, et couvre uniformément le territoire.
        _lons = np.arange(-5.5, 10.51, 0.1)
        _lats = np.arange(41.0, 51.51, 0.1)
        _lv, _ltv = np.meshgrid(_lons, _lats)
        arome_points = np.column_stack([_lv.ravel(), _ltv.ravel()])  # (lon, lat)

        try:
            df_arome = fetch_arome_for_day(day, arome_points, max_hours=24)

            if not df_arome.empty:
                arome_file = DAILY_DIR / f"arome_{day.strftime('%Y%m%d')}.csv"
                df_arome.to_csv(arome_file, index=False)
                logging.info(f"✓ AROME data saved to {arome_file} ({len(df_arome)} points)")
            else:
                logging.warning("✗ AROME processing returned empty dataframe — will retry next run")
        except Exception as e:
            logging.error(f"✗ AROME processing failed: {e} — will retry next run")
    else:
        csv_mtime = datetime.fromtimestamp(arome_csv_today.stat().st_mtime, tz=TZ)
        next_fetch = csv_mtime + timedelta(hours=6)
        logging.info(
            f"✓ AROME fetch not needed — CSV du jour créé à {csv_mtime.strftime('%H:%M')} UTC, "
            f"prochain fetch à {next_fetch.strftime('%H:%M')} UTC"
        )
    
    # ==================== 5. INTERPRET_DAY (après toutes les sources) ====================
    # Appelé en dernier pour avoir radar + stations + AROME disponibles
    logging.info("\n[5/5] Running interpret_day...")
    try:
        from interpret_day import interpret_day as interpret_day_func
        interpret_day_func(day)
        logging.info("✓ interpret_day completed — GeoTIFFs et tuiles mis à jour")
    except Exception as e:
        logging.warning(f"✗ interpret_day failed: {e}")

    # ==================== FIN ====================
    elapsed = time.time() - start_time
    logging.info("=" * 60)
    logging.info(f"COLLECTION COMPLETED IN {elapsed:.1f} SECONDS")
    logging.info("=" * 60)

if __name__ == "__main__":
    main()