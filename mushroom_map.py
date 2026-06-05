#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Carte de probabilité « coins à champignons » + détection d'essence au point.

Deux briques, séparées par fiabilité :

1. NATIONAL (le « où ») — overlay de favorabilité = densité forestière × météo
   récente. La densité forestière provient de la BD Forêt® V2 (IGN) rendue en WMS
   et agrégée par maille km. On n'utilise QUE la présence/densité de forêt (canal
   alpha), parfaitement fiable, et non la couleur (essence) : à l'échelle km le
   rendu WMS est trop anti-aliasé pour décoder l'essence de façon fiable.

2. AU POINT (le « quoi ») — forest_at_point() interroge le WMS (GetFeatureInfo) à
   pleine résolution et renvoie l'ESSENCE EXACTE (chênes, hêtre, pin maritime,
   sapin/épicéa…). C'est ce qui permet de lister les champignons réellement
   associés à l'arbre-hôte local.

La grille de référence est celle des rasters météo (RR_*.tif / T_*.tif) :
EPSG:4326, 1601×1051, origine (-5.505, 51.505), pas 0.01°.
"""

from __future__ import annotations
import io
import math
import urllib.request
import urllib.parse
from pathlib import Path

import numpy as np

WMS_URL = "https://data.geopf.fr/wms-r/wms"
FOREST_LAYER = "LANDCOVER.FORESTINVENTORY.V2"

# Grille de référence (identique aux rasters météo). Validée :
#   bounds left=-5.505 top=51.505, res 0.01°, shape (1051, 1601).
GRID_W, GRID_H = 1601, 1051
GRID_LEFT, GRID_TOP, GRID_RES = -5.505, 51.505, 0.01
# BBOX WMS 1.3.0 EPSG:4326 = miny,minx,maxy,maxx
_GRID_BBOX_4326 = "40.995,-5.505,51.505,10.505"

CACHE_DIR = Path("data/cache")
_DENSITY_NPY = CACHE_DIR / "forest_density_1km.npy"
# Tuile hi-res (~355 m/px) servant à dériver la densité ; sous la limite WMS 5010 px.
_HIRES_W, _HIRES_H = 5010, 3288


# --------------------------------------------------------------------------- #
#  1. Densité forestière nationale (raster 1 km, fiable)
# --------------------------------------------------------------------------- #
def _fetch_forest_hires_png() -> bytes:
    params = {
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap",
        "LAYERS": FOREST_LAYER, "STYLES": "normal", "CRS": "EPSG:4326",
        "BBOX": _GRID_BBOX_4326, "WIDTH": str(_HIRES_W), "HEIGHT": str(_HIRES_H),
        "FORMAT": "image/png", "TRANSPARENT": "TRUE",
    }
    url = WMS_URL + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=180) as r:
        return r.read()


def build_forest_density() -> np.ndarray:
    """Construit la densité forestière par maille km (fraction 0..1) à partir du
    canal alpha de la BD Forêt rendue en hi-res. Met en cache un .npy."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    png = _fetch_forest_hires_png()
    a = np.array(Image.open(io.BytesIO(png)).convert("RGBA"))
    H, W = a.shape[:2]
    op = (a[..., 3] > 150).astype(np.float32)  # opaque = polygone forêt présent

    sx, sy = W / GRID_W, H / GRID_H
    col_edges = [int(C * sx) for C in range(GRID_W)]
    seg_w = np.diff(col_edges + [W])
    dens = np.zeros((GRID_H, GRID_W), dtype=np.float32)
    for R in range(GRID_H):
        r0 = int(R * sy)
        r1 = max(r0 + 1, int((R + 1) * sy))
        block = op[r0:r1]
        col_sums = np.add.reduceat(block, col_edges, axis=1)
        dens[R] = col_sums.sum(0) / (block.shape[0] * seg_w)
    dens = np.clip(dens, 0.0, 1.0).astype(np.float32)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.save(_DENSITY_NPY, dens)
    return dens


def load_forest_density(force_rebuild: bool = False) -> np.ndarray | None:
    """Charge la densité forestière (cache .npy), la construit si absente.
    Renvoie None si le WMS est injoignable et qu'aucun cache n'existe."""
    if not force_rebuild and _DENSITY_NPY.exists():
        try:
            arr = np.load(_DENSITY_NPY)
            if arr.shape == (GRID_H, GRID_W):
                return arr
        except Exception:
            pass
    try:
        return build_forest_density()
    except Exception:
        return None


# --------------------------------------------------------------------------- #
#  2. Essence exacte au point (WMS GetFeatureInfo, haute résolution)
# --------------------------------------------------------------------------- #
def _lonlat_to_merc(lon: float, lat: float) -> tuple[float, float]:
    x = lon * 20037508.34 / 180.0
    y = math.log(math.tan((90 + lat) * math.pi / 360.0)) / (math.pi / 180.0) * 20037508.34 / 180.0
    return x, y


def forest_at_point(lat: float, lon: float) -> dict | None:
    """Interroge la BD Forêt au point (lat, lon). Renvoie un dict
    {essence, tfv, tfv_g11, family} ou None si hors forêt / erreur."""
    import json
    cx, cy = _lonlat_to_merc(lon, lat)
    d = 120  # demi-fenêtre en mètres autour du point
    params = {
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo",
        "LAYERS": FOREST_LAYER, "QUERY_LAYERS": FOREST_LAYER,
        "CRS": "EPSG:3857", "BBOX": f"{cx-d},{cy-d},{cx+d},{cy+d}",
        "WIDTH": "5", "HEIGHT": "5", "I": "2", "J": "2",
        "INFO_FORMAT": "application/json", "FORMAT": "image/png", "STYLES": "normal",
    }
    url = WMS_URL + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=5) as r:   # court : ne pas bloquer un thread si l'IGN traîne
            feats = json.loads(r.read().decode("utf-8", "ignore")).get("features", [])
    except Exception:
        return None
    if not feats:
        return None
    p = feats[0].get("properties", {})
    tfv_g11 = p.get("tfv_g11", "") or ""
    essence = p.get("essence", "") or ""
    return {
        "essence": essence,
        "tfv": p.get("tfv", "") or "",
        "tfv_g11": tfv_g11,
        "family": _family_from_strings(tfv_g11, essence, p.get("tfv", "")),
    }


def _family_from_strings(tfv_g11: str, essence: str, tfv: str) -> str:
    """Réduit la classe BD Forêt à une famille d'hôte large :
    'feuillus' | 'coniferes' | 'mixte' | 'peupleraie' | 'ouvert'."""
    s = (tfv_g11 + " " + essence + " " + tfv).lower()
    if "peupl" in s:
        return "peupleraie"
    if "mixte" in s or ("feuillus" in s and ("conif" in s or "résineux" in s)):
        return "mixte"
    if "conif" in s or any(k in s for k in ("pin", "sapin", "épicéa", "epicea", "douglas", "mélèze", "meleze", "résineux")):
        return "coniferes"
    if "feuillus" in s or any(k in s for k in ("chêne", "chene", "hêtre", "hetre", "châtaignier", "chataignier", "robinier", "frêne", "charme")):
        return "feuillus"
    if any(k in s for k in ("lande", "herbac", "sans couvert")):
        return "ouvert"
    return "ouvert"


# --------------------------------------------------------------------------- #
#  2bis. Famille d'hôte au point depuis les rasters BAKÉS (instantané, hors-ligne)
# --------------------------------------------------------------------------- #
# Évite l'appel WMS bloquant de forest_at_point pour le chemin critique du clic :
# la famille (feuillus/conifères/mixte), qui pilote host_match, est lue dans les
# fractions bakées host_*.npy (mêmes données que le SDM). Le libellé d'essence
# précis (tfv) reste fourni à la demande par forest_at_point (WMS, différé).
_HOST_NPY = {
    "feuillus":  CACHE_DIR / "host_broadleaf.npy",
    "coniferes": CACHE_DIR / "host_needleleaf.npy",
    "mixte":     CACHE_DIR / "host_mixed.npy",
}
_host_cache: dict[str, np.ndarray] = {}
FOREST_MIN_FAMILY = 0.05   # densité forêt en deçà de laquelle : hors forêt


def _load_host_layers() -> dict[str, np.ndarray]:
    """Charge (cache module, lazy) les fractions broadleaf/needleleaf/mixed bakées."""
    if not _host_cache:
        for fam, p in _HOST_NPY.items():
            try:
                if p.exists():
                    arr = np.load(p)
                    if arr.shape == (GRID_H, GRID_W):
                        _host_cache[fam] = arr
            except Exception:
                pass
    return _host_cache


def family_at_point(lat: float, lon: float) -> dict | None:
    """Famille d'hôte au point, lue dans les rasters bakés — INSTANTANÉ, sans appel
    réseau (≠ forest_at_point/WMS). Mêmes clés que forest_at_point ; essence/tfv à
    None (le libellé précis est fourni plus tard par la WMS via /api/forest)."""
    col = int((lon - GRID_LEFT) / GRID_RES)
    row = int((GRID_TOP - lat) / GRID_RES)
    if not (0 <= row < GRID_H and 0 <= col < GRID_W):
        return None
    dens_arr = load_forest_density()
    dens = None
    if dens_arr is not None and np.isfinite(dens_arr[row, col]):
        dens = float(dens_arr[row, col])
    base = {"essence": None, "tfv": None, "tfv_g11": None, "density": dens}

    layers = _load_host_layers()
    b = float(layers["feuillus"][row, col])  if "feuillus"  in layers and np.isfinite(layers["feuillus"][row, col])  else 0.0
    n = float(layers["coniferes"][row, col]) if "coniferes" in layers and np.isfinite(layers["coniferes"][row, col]) else 0.0
    m = float(layers["mixte"][row, col])     if "mixte"     in layers and np.isfinite(layers["mixte"][row, col])     else 0.0
    tot = b + n + m

    # Hors forêt : densité trop faible OU aucune fraction d'hôte → famille inconnue
    # (host_match neutre, fiche « hors forêt cartographiée »), comme l'ancien WMS sans feature.
    if (dens is not None and dens < FOREST_MIN_FAMILY) or tot <= 0:
        return {**base, "family": None}

    # Famille dominante ; broadleaf+needleleaf comparables → mixte.
    if m >= max(b, n) or (min(b, n) >= 0.25 * tot):
        fam = "mixte"
    elif b >= n:
        fam = "feuillus"
    else:
        fam = "coniferes"
    return {**base, "family": fam}


# --------------------------------------------------------------------------- #
#  Associations essence ↔ champignons (mycorhize / saprophytie)
# --------------------------------------------------------------------------- #
# Chaque champignon (clé = nom latin) est rattaché à des familles d'hôte et/ou
# à l'habitat ouvert (prés/lisières). Sert au tri/annotation du guide au point
# ET au choix des espèces « forestières » qui pilotent la heatmap nationale.
#   families : sous-ensemble de {'feuillus','coniferes','peupleraie'}
#   open     : True si pousse aussi/surtout en milieu ouvert (prés, lisières)
MUSHROOM_HOSTS = {
    "Morchella esculenta":          {"families": {"feuillus"}, "open": True},
    "Calocybe gambosa":             {"families": set(), "open": True},
    "Boletus aereus":               {"families": {"feuillus"}, "open": False},
    "Cantharellus cibarius":        {"families": {"feuillus", "coniferes"}, "open": False},
    "Boletus edulis":               {"families": {"feuillus", "coniferes"}, "open": False},
    "Macrolepiota procera":         {"families": set(), "open": True},
    "Agaricus campestris":          {"families": set(), "open": True},
    "Craterellus cornucopioides":   {"families": {"feuillus"}, "open": False},
    "Craterellus tubaeformis":      {"families": {"coniferes"}, "open": False},
    "Hydnum repandum":              {"families": {"feuillus", "coniferes"}, "open": False},
    "Lactarius deliciosus":         {"families": {"coniferes"}, "open": False},
    "Imleria badia":                {"families": {"coniferes", "feuillus"}, "open": False},
    "Lepista nuda":                 {"families": {"feuillus"}, "open": True},
    "Pleurotus ostreatus":          {"families": {"feuillus", "peupleraie"}, "open": False},
}


def host_match(latin: str, family: str | None) -> str:
    """Renvoie 'ok' (hôte présent), 'no' (hôte absent ici) ou 'unknown'."""
    info = MUSHROOM_HOSTS.get(latin)
    if info is None or family is None:
        return "unknown"
    if family in info["families"]:
        return "ok"
    if family in ("peupleraie",) and "peupleraie" in info["families"]:
        return "ok"
    if family == "ouvert" and info["open"]:
        return "ok"
    if family == "mixte" and info["families"]:
        return "ok"  # mixte contient feuillus ET conifères
    return "no"


# --------------------------------------------------------------------------- #
#  3. Favorabilité par maille (national)
# --------------------------------------------------------------------------- #
def _read_grid_raster(path: Path):
    """Lit un GeoTIFF de la grille → (H,W) float32, nodata→NaN, ou None."""
    import rasterio
    try:
        with rasterio.open(path) as src:
            arr = src.read(1).astype(np.float32)
            if src.nodata is not None:
                arr[arr == src.nodata] = np.nan
        return arr
    except Exception:
        return None


def _load_windows(data_dir: Path, ref_date, available_dates,
                  rain_windows=(7, 14), temp_days=14):
    """Empile les rasters RR/T récents et renvoie
    (rain7, rain14, temp_mean) sur la grille (None si indisponible)."""
    import datetime as _dt
    data_dir = Path(data_dir)
    maxwin = max(rain_windows + (temp_days,))
    rains = {w: [] for w in rain_windows}
    temps = []
    for ds in available_dates:
        d = _dt.datetime.strptime(ds, "%Y%m%d").date()
        delta = (ref_date - d).days
        if not (0 <= delta <= maxwin):
            continue
        rr = _read_grid_raster(data_dir / f"RR_{ds}.tif")
        if rr is not None:
            for w in rain_windows:
                if delta <= w:
                    rains[w].append(rr)
        if delta <= temp_days:
            tt = _read_grid_raster(data_dir / f"T_{ds}.tif")
            if tt is not None:
                temps.append(tt)
    out = []
    for w in rain_windows:
        out.append(np.nansum(np.stack(rains[w]), axis=0) if rains[w] else None)
    temp_mean = np.nanmean(np.stack(temps), axis=0) if temps else None
    return out[0], out[1], temp_mean


def _latest_soil_grid(data_dir: Path, prefix: str, ref_date):
    """Charge le raster sol PREFIX_*.tif (SM/TS) le plus récent ≤ ref_date.
    Le sol n'étant rafraîchi qu'~1×/jour, on tolère un léger décalage."""
    import datetime as _dt
    best = None
    for f in Path(data_dir).glob(f"{prefix}_*.tif"):
        try:
            d = _dt.datetime.strptime(f.stem.split("_")[-1], "%Y%m%d").date()
        except Exception:
            continue
        if d <= ref_date and (best is None or d > best[0]):
            best = (d, f)
    return _read_grid_raster(best[1]) if best else None


def _nan_to(arr, fill):
    return np.where(np.isnan(arr), fill, arr)


def _moisture_fit(soil_moist, rain7, rain14):
    """Facteur humidité 0..1 : combine l'humidité du sol (état intégré) et les
    cumuls de pluie 7 j / 14 j. Pondération adaptative aux sources présentes."""
    parts = []  # (array, weight)
    if soil_moist is not None:
        smf = np.clip((soil_moist - 0.08) / (0.30 - 0.08), 0.0, 1.0)
        parts.append((smf, 0.5, soil_moist))
    if rain14 is not None:
        parts.append((np.clip(rain14 / 40.0, 0.0, 1.0), 0.3, rain14))
    if rain7 is not None:
        parts.append((np.clip(rain7 / 22.0, 0.0, 1.0), 0.2, rain7))
    if not parts:
        return np.full((GRID_H, GRID_W), 0.4, dtype=np.float32)
    num = np.zeros((GRID_H, GRID_W), np.float32)
    den = np.zeros((GRID_H, GRID_W), np.float32)
    for fit, w, raw in parts:
        valid = ~np.isnan(raw)
        num += np.where(valid, _nan_to(fit, 0.0) * w, 0.0)
        den += np.where(valid, w, 0.0)
    return np.where(den > 0, num / den, 0.4).astype(np.float32)


def _ph_fit(ph_grid, lo, hi, margin=0.8):
    """Adéquation pH (0.2..1) : 1 dans [lo,hi], chute linéaire sur `margin`,
    plancher 0.2 (le pH ne doit jamais annuler seul une maille). pH inconnu→0.6."""
    if ph_grid is None:
        return np.full((GRID_H, GRID_W), 0.85, dtype=np.float32)
    below = np.clip((lo - ph_grid) / margin, 0, 1)
    above = np.clip((ph_grid - hi) / margin, 0, 1)
    f = np.clip(1.0 - below - above, 0.0, 1.0)
    f = np.where(np.isnan(ph_grid), 0.6, f)
    return (0.2 + 0.8 * f).astype(np.float32)


def _texture_fit(silt, clay):
    """Facteur texture 0.7..1 : favorise les sols équilibrés (limons), pénalise
    légèrement les extrêmes (sable très drainant / argile asphyxiante)."""
    if silt is None or clay is None:
        return np.full((GRID_H, GRID_W), 1.0, dtype=np.float32)
    fine = silt + clay  # fraction fine (%)
    retention = np.clip(0.1 + 0.8 * fine / 100.0, 0.0, 1.0)
    tf = np.clip(1.0 - 0.3 * np.abs(retention - 0.6) / 0.6, 0.7, 1.0)
    return np.where(np.isnan(fine), 1.0, tf).astype(np.float32)


def _eff_temp(temp_air, soil_temp):
    """Température effective de fructification : moyenne air/sol quand le sol est
    disponible (le mycélium répond à la T° du sol), sinon l'air seul."""
    if soil_temp is None:
        return temp_air
    if temp_air is None:
        return soil_temp
    return np.where(np.isnan(soil_temp), temp_air,
                    np.where(np.isnan(temp_air), soil_temp,
                             0.5 * temp_air + 0.5 * soil_temp))


def _altitude_fit(alt_grid, alt_opt):
    """Facteur altitude 0.3..1 (par espèce). Pénalité douce au-dessus de la
    limite forestière (~1800 m) + fenêtre optionnelle alt_opt=(lo,hi) en m."""
    if alt_grid is None:
        return np.ones((GRID_H, GRID_W), dtype=np.float32)
    # limite forestière : 1 jusqu'à 1800 m, descend vers 0.4 à 2400 m
    treeline = 1.0 - np.clip((alt_grid - 1800.0) / 600.0, 0.0, 0.6)
    if alt_opt:
        lo, hi = alt_opt
        margin = 400.0
        below = np.clip((lo - alt_grid) / margin, 0, 1)
        above = np.clip((alt_grid - hi) / margin, 0, 1)
        window = np.clip(1.0 - below - above, 0.0, 1.0)
        window = 0.4 + 0.6 * window
    else:
        window = 1.0
    f = np.clip(treeline * window, 0.3, 1.0)
    return np.where(np.isnan(alt_grid), 1.0, f).astype(np.float32)


# Pondération exposition par mois : >0 favorise les versants nord (frais/humides),
# <0 favorise les versants sud (plus chauds). Été→nord, fin d'automne/hiver→sud.
_ASPECT_W = {1: -0.10, 2: -0.10, 3: 0.05, 4: 0.05, 5: 0.05, 6: 0.10,
             7: 0.10, 8: 0.10, 9: -0.05, 10: -0.05, 11: -0.10, 12: -0.10}


def _aspect_fit(north_grid, month):
    """Facteur exposition 0.85..1.15 (commun, saisonnier) via northness
    (+1=nord, -1=sud). Terrain plat (northness≈0) → ≈1."""
    if north_grid is None:
        return np.ones((GRID_H, GRID_W), dtype=np.float32)
    w = _ASPECT_W.get(month, 0.0)
    f = np.clip(1.0 + w * north_grid, 0.85, 1.15)
    return np.where(np.isnan(north_grid), 1.0, f).astype(np.float32)


def compute_favorability(mushrooms, ref_date_str, available_dates, data_dir):
    """Favorabilité champignons par maille (0..1) — modèle v2 enrichi sol.

        fav = densité_forêt^0.6
              × max_s( temp_fit_s × ph_fit_s )      (meilleure espèce en saison)
              × moisture_fit                         (humidité sol + pluie 7/14 j)
              × texture_fit                          (type de sol)

    temp_fit mélange T° air (14 j) et T° sol (6 cm) ; moisture_fit combine
    l'humidité du sol et les cumuls de pluie ; ph_fit/texture_fit viennent des
    couches SoilGrids. Renvoie {'fav','density','season_species','has_weather',
    'has_soil'} ou None si la densité forêt est indisponible.
    """
    import datetime as _dt
    density = load_forest_density()
    if density is None:
        return None

    ref = _dt.datetime.strptime(ref_date_str, "%Y%m%d").date()
    month = ref.month
    rain7, rain14, temp_mean = _load_windows(Path(data_dir), ref, available_dates)
    has_weather = temp_mean is not None

    # --- Couches sol : dynamique (SM/TS) + statique (pH/texture) -------------
    soil_moist = _latest_soil_grid(data_dir, "SM", ref)
    soil_temp = _latest_soil_grid(data_dir, "TS", ref)
    ph_grid = silt_grid = clay_grid = None
    try:
        import soil_data
        static = soil_data.load_soil_static()
        if static is not None:
            ph_grid, silt_grid, clay_grid = static["ph"], static["silt"], static["clay"]
    except Exception:
        pass
    has_soil = soil_moist is not None or ph_grid is not None

    # --- Relief : altitude + exposition (versants) ---------------------------
    alt_grid = north_grid = None
    try:
        import terrain_data
        terr = terrain_data.load_terrain_static()
        if terr is not None:
            alt_grid, north_grid = terr["altitude"], terr["northness"]
    except Exception:
        pass
    has_terrain = alt_grid is not None

    # Espèces forestières en saison (hôte forestier connu + mois courant)
    season_species = [
        m for m in mushrooms
        if month in m["months"] and MUSHROOM_HOSTS.get(m.get("latin", ""), {}).get("families")
    ]

    if not season_species:
        fav = (density ** 0.6) * 0.12  # hors-saison forestière : forêts à peine visibles
        return {"fav": fav.astype(np.float32), "density": density, "season_species": [],
                "has_weather": has_weather, "has_soil": has_soil, "has_terrain": has_terrain}

    # Facteurs communs (humidité, texture, exposition saisonnière).
    moisture = _moisture_fit(soil_moist, rain7, rain14)
    texture = _texture_fit(silt_grid, clay_grid)
    aspect = _aspect_fit(north_grid, month)
    eff_temp = _eff_temp(temp_mean, soil_temp)

    best = np.zeros((GRID_H, GRID_W), dtype=np.float32)
    for m in season_species:
        if eff_temp is not None:
            lo, hi = m["t_min"], m["t_max"]
            width = max(2.0, (hi - lo))
            below = np.clip((lo - eff_temp) / width, 0, 1)
            above = np.clip((eff_temp - hi) / width, 0, 1)
            tfac = np.clip(1.0 - below - above, 0.0, 1.0)
            tfac = _nan_to(tfac, 0.5)
        else:
            tfac = np.full((GRID_H, GRID_W), 0.5, dtype=np.float32)
        ph_lo, ph_hi = m.get("ph_opt", (4.0, 8.5))
        phf = _ph_fit(ph_grid, ph_lo, ph_hi)
        altf = _altitude_fit(alt_grid, m.get("alt_opt"))
        best = np.maximum(best, tfac * phf * altf)

    fav = (density ** 0.6) * best * moisture * texture * aspect
    # Maille non forestière → quasi nul (transparent au rendu)
    fav = np.where(density < 0.04, 0.0, fav).astype(np.float32)
    return {"fav": fav, "density": density,
            "season_species": [m["nom"] for m in season_species],
            "has_weather": has_weather, "has_soil": has_soil, "has_terrain": has_terrain}
