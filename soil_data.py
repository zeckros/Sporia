#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Données pédologiques (type de sol) — Python pur, sans clé API.

Deux briques, comme mushroom_map.py :

1. NATIONAL (le « où ») — couches statiques bakées une fois sur la grille météo
   (1601×1051, EPSG:4326) à partir de SoilGrids 250 m (ISRIC) via WCS :
     • argile / sable / limon (% — texture),
     • pH (eau).
   Mises en cache en .npy (data/cache/soil_*.npy). Le sol ne changeant pas, le
   bake est unique. Sert au calcul de favorabilité national.

2. AU POINT (le « quoi ») — soil_at_point() interroge l'API REST SoilGrids à
   pleine résolution pour un point (lat, lon) et renvoie texture + pH + classe
   USDA. Sert au rapport de point / guide.

Unités SoilGrids : argile/sable/limon en g/kg (÷10 → %), pH en pH×10 (÷10).
La grille est alignée sur les rasters météo RR_*.tif / T_*.tif (interpret_day).
"""
from __future__ import annotations
import io
import time
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

import numpy as np

# --- Grille de référence : alignée pixel-à-pixel sur les rasters météo --------
# interpret_day : centres -5.5..10.5 / 51.5..41.0, RES 0.01 → 1601×1051.
# Bords (edges) = centres ± RES/2.
GRID_W, GRID_H = 1601, 1051
GRID_RES = 0.01
_EDGE_LEFT, _EDGE_RIGHT = -5.505, 10.505
_EDGE_BOTTOM, _EDGE_TOP = 40.995, 51.505

CACHE_DIR = Path("data/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Propriétés SoilGrids et fichiers cache associés (clé interne → coverage SoilGrids).
SOIL_PROPS = {"clay": "clay", "sand": "sand", "silt": "silt", "phh2o": "phh2o"}
# Profondeurs moyennées → topsoil 0–15 cm (zone du mycélium / horizon de surface).
SOIL_DEPTHS = ["0-5cm", "5-15cm"]

_WCS_BASE = "https://maps.isric.org/mapserv?map=/map/{prop}.map"
_REST_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"


# --------------------------------------------------------------------------- #
#  1. Bake national (WCS → grille .npy)
# --------------------------------------------------------------------------- #
def _wcs_property_depth(prop: str, depth: str) -> np.ndarray | None:
    """Récupère une propriété SoilGrids à une profondeur sur la grille France
    (1601×1051, EPSG:4326). Renvoie un (H,W) float32 en unités brutes (×10),
    NaN hors-sol, ou None si le WCS est injoignable."""
    import rasterio
    base = _WCS_BASE.format(prop=prop)
    params = {
        "SERVICE": "WCS", "VERSION": "2.0.1", "REQUEST": "GetCoverage",
        "COVERAGEID": f"{prop}_{depth}_mean",
        "FORMAT": "image/tiff",
        "SUBSET": [f"X({_EDGE_LEFT},{_EDGE_RIGHT})", f"Y({_EDGE_BOTTOM},{_EDGE_TOP})"],
        "SUBSETTINGCRS": "http://www.opengis.net/def/crs/EPSG/0/4326",
        "OUTPUTCRS": "http://www.opengis.net/def/crs/EPSG/0/4326",
        "SCALESIZE": f"X({GRID_W}),Y({GRID_H})",
    }
    url = base + "&" + urllib.parse.urlencode(params, doseq=True)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                payload = r.read()
            with rasterio.MemoryFile(payload) as mem, mem.open() as src:
                arr = src.read(1).astype(np.float32)
                nod = src.nodata
            if nod is not None:
                arr[arr == nod] = np.nan
            arr[arr <= 0] = np.nan  # 0 = océan / hors couverture SoilGrids
            if arr.shape != (GRID_H, GRID_W):
                # SCALESIZE peut produire ±1 px ; recadre/complète défensivement.
                fixed = np.full((GRID_H, GRID_W), np.nan, np.float32)
                h, w = min(arr.shape[0], GRID_H), min(arr.shape[1], GRID_W)
                fixed[:h, :w] = arr[:h, :w]
                arr = fixed
            return arr
        except Exception:
            if attempt < 2:
                time.sleep(4)
    return None


def build_soil_static(force: bool = False) -> dict | None:
    """Bake les couches sol (argile/sable/limon en %, pH) sur la grille et les
    met en cache (.npy). Renvoie {'clay','sand','silt','ph'} (arrays %) ou None
    si le WCS est injoignable. Texture renormalisée à 100 %."""
    out_files = {k: CACHE_DIR / f"soil_{k}.npy" for k in ("clay", "sand", "silt", "ph")}
    if not force and all(f.exists() for f in out_files.values()):
        loaded = load_soil_static()
        if loaded is not None:
            return loaded

    raw: dict[str, np.ndarray] = {}
    for prop in ("clay", "sand", "silt", "phh2o"):
        layers = []
        for depth in SOIL_DEPTHS:
            a = _wcs_property_depth(prop, depth)
            if a is not None:
                layers.append(a)
        if not layers:
            return None  # source indisponible → on ne casse pas un cache existant
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)  # mean of all-NaN cells
            raw[prop] = np.nanmean(np.stack(layers), axis=0)

    # g/kg → % ; pH×10 → pH
    clay = raw["clay"] / 10.0
    sand = raw["sand"] / 10.0
    silt = raw["silt"] / 10.0
    ph = raw["phh2o"] / 10.0

    # Renormalise la texture à 100 % (corrige arrondis SoilGrids).
    total = clay + sand + silt
    with np.errstate(invalid="ignore"):
        scale = np.where(total > 0, 100.0 / total, np.nan)
    clay, sand, silt = clay * scale, sand * scale, silt * scale

    grids = {"clay": clay.astype(np.float32), "sand": sand.astype(np.float32),
             "silt": silt.astype(np.float32), "ph": ph.astype(np.float32)}
    for k, arr in grids.items():
        try:
            np.save(out_files[k], arr)
        except Exception:
            pass
    return grids


_SOIL_CACHE: dict | None = None


def load_soil_static() -> dict | None:
    """Charge les couches sol bakées (.npy) — LECTURE SEULE (ne bake jamais dans
    le chemin requête : le bake est fait par le scheduler/CLI). Renvoie
    {'clay','sand','silt','ph'} ou None si absent ; ne met en cache qu'un succès."""
    global _SOIL_CACHE
    if _SOIL_CACHE is not None:
        return _SOIL_CACHE
    out_files = {k: CACHE_DIR / f"soil_{k}.npy" for k in ("clay", "sand", "silt", "ph")}
    if all(f.exists() for f in out_files.values()):
        try:
            grids = {k: np.load(f) for k, f in out_files.items()}
            if all(g.shape == (GRID_H, GRID_W) for g in grids.values()):
                _SOIL_CACHE = grids
                return grids
        except Exception:
            pass
    return None


# --------------------------------------------------------------------------- #
#  2. Classification texturale (triangle USDA)
# --------------------------------------------------------------------------- #
# Clé USDA → (label FR, descripteur rétention/drainage pour le modèle).
TEXTURE_FR = {
    "sand":            "Sable",
    "loamy_sand":      "Sable limoneux",
    "sandy_loam":      "Limon sableux",
    "loam":            "Limon (terre franche)",
    "silt_loam":       "Limon fin",
    "silt":            "Limon très fin",
    "sandy_clay_loam": "Limon argilo-sableux",
    "clay_loam":       "Limon argileux",
    "silty_clay_loam": "Limon argilo-limoneux",
    "sandy_clay":      "Argile sableuse",
    "silty_clay":      "Argile limoneuse",
    "clay":            "Argile",
}
# Ordre canonique des classes (indices utilisés par texture_class_grid / overlay).
CLASS_ORDER = list(TEXTURE_FR.keys())

# Capacité de rétention d'eau ≈ par texture (0 sableux/drainant → 1 argileux/rétenteur).
TEXTURE_RETENTION = {
    "sand": 0.10, "loamy_sand": 0.25, "sandy_loam": 0.40, "loam": 0.60,
    "silt_loam": 0.65, "silt": 0.62, "sandy_clay_loam": 0.55, "clay_loam": 0.75,
    "silty_clay_loam": 0.80, "sandy_clay": 0.70, "silty_clay": 0.85, "clay": 0.90,
}


def usda_texture(sand: float, silt: float, clay: float) -> str:
    """Classe texturale USDA (12 classes) à partir des % sable/limon/argile.
    Renvoie une clé de TEXTURE_FR."""
    s, m, c = float(sand), float(silt), float(clay)
    if c >= 40:
        if m >= 40:
            return "silty_clay"
        if s <= 45:
            return "clay"
        return "sandy_clay"
    if c >= 35 and s >= 45:
        return "sandy_clay"
    if c >= 27:
        if s <= 20:
            return "silty_clay_loam"
        if s <= 45:
            return "clay_loam"
        return "sandy_clay_loam"
    # c < 27
    if m >= 80 and c < 12:
        return "silt"
    if m >= 50 and (c < 27):
        if c < 12 and m < 80:
            return "silt_loam"
        if 12 <= c < 27:
            return "silt_loam"
    if c >= 20 and m < 28 and s > 45:
        return "sandy_clay_loam"
    if 7 <= c < 27 and 28 <= m < 50 and s <= 52:
        return "loam"
    if s >= 85 and (m + 1.5 * c) < 15:
        return "sand"
    if 70 <= s and (m + 1.5 * c) >= 15 and (m + 2 * c) < 30:
        return "loamy_sand"
    # défaut : sandy_loam (large coin sableux du triangle)
    return "sandy_loam"


def texture_class_grid(sand, silt, clay):
    """Version vectorisée de usda_texture sur des grilles (%). Renvoie un int16
    d'indices dans CLASS_ORDER, -1 = sans donnée. Mêmes règles/ordre que le
    classement scalaire (np.select = équivalent du if/elif)."""
    s = np.asarray(sand, dtype=np.float32)
    m = np.asarray(silt, dtype=np.float32)
    c = np.asarray(clay, dtype=np.float32)
    nod = ~(np.isfinite(s) & np.isfinite(m) & np.isfinite(c))
    s = np.where(nod, 0.0, s)
    m = np.where(nod, 0.0, m)
    c = np.where(nod, 0.0, c)
    i = {k: n for n, k in enumerate(CLASS_ORDER)}
    conds = [
        (c >= 40) & (m >= 40),                                   # silty_clay
        (c >= 40) & (s <= 45),                                   # clay
        (c >= 40),                                               # sandy_clay
        (c >= 35) & (s >= 45),                                   # sandy_clay
        (c >= 27) & (s <= 20),                                   # silty_clay_loam
        (c >= 27) & (s <= 45),                                   # clay_loam
        (c >= 27),                                               # sandy_clay_loam
        (m >= 80) & (c < 12),                                    # silt
        (m >= 50) & (c < 27),                                    # silt_loam
        (c >= 20) & (m < 28) & (s > 45),                         # sandy_clay_loam
        (c >= 7) & (c < 27) & (m >= 28) & (m < 50) & (s <= 52),  # loam
        (s >= 85) & ((m + 1.5 * c) < 15),                        # sand
        (s >= 70) & ((m + 1.5 * c) >= 15) & ((m + 2 * c) < 30),  # loamy_sand
    ]
    choices = [i["silty_clay"], i["clay"], i["sandy_clay"], i["sandy_clay"],
               i["silty_clay_loam"], i["clay_loam"], i["sandy_clay_loam"],
               i["silt"], i["silt_loam"], i["sandy_clay_loam"], i["loam"],
               i["sand"], i["loamy_sand"]]
    out = np.select(conds, choices, default=i["sandy_loam"]).astype(np.int16)
    out[nod] = -1
    return out


def ph_class_fr(ph: float | None) -> str:
    if ph is None or not np.isfinite(np.asarray(ph, dtype=float)):
        return "inconnu"
    ph = float(ph)
    if ph < 5.0:
        return "très acide"
    if ph < 5.5:
        return "acide"
    if ph < 6.5:
        return "légèrement acide"
    if ph < 7.2:
        return "neutre"
    if ph < 7.8:
        return "légèrement basique"
    return "calcaire / basique"


def describe_soil(sand, silt, clay, ph) -> dict:
    """Assemble un descripteur sol prêt pour l'affichage et le modèle."""
    def _f(x):
        # robuste aux float numpy (np.float32/64) ET python : NaN/inf → None
        if x is None:
            return None
        try:
            xf = float(x)
        except (TypeError, ValueError):
            return None
        return None if not np.isfinite(xf) else xf
    sand, silt, clay, ph = _f(sand), _f(silt), _f(clay), _f(ph)
    if None in (sand, silt, clay):
        key = None
    else:
        key = usda_texture(sand, silt, clay)
    return {
        "sand": round(sand, 1) if sand is not None else None,
        "silt": round(silt, 1) if silt is not None else None,
        "clay": round(clay, 1) if clay is not None else None,
        "ph": round(ph, 1) if ph is not None else None,
        "texture": key,
        "texture_fr": TEXTURE_FR.get(key) if key else None,
        "ph_class": ph_class_fr(ph),
        "retention": TEXTURE_RETENTION.get(key) if key else None,
    }


# --------------------------------------------------------------------------- #
#  3. Sol au point (REST SoilGrids, haute résolution)
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=4096)
def soil_at_point(lat: float, lon: float) -> dict | None:
    """Interroge SoilGrids REST au point (lat, lon) — texture topsoil 0–15 cm +
    pH. Renvoie describe_soil(...) ou None si injoignable. Mis en cache (le sol
    ne change pas) pour respecter la limite de l'API REST (~5 req/min)."""
    import json
    params = [("lon", lon), ("lat", lat),
              ("property", "clay"), ("property", "sand"),
              ("property", "silt"), ("property", "phh2o"),
              ("depth", "0-5cm"), ("depth", "5-15cm"), ("value", "mean")]
    url = _REST_URL + "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(
        url, headers={"User-Agent": "Sporia/1.0 (mushroom map)", "Accept": "application/json"})
    j = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.loads(r.read().decode("utf-8", "ignore"))
            break
        except Exception:
            if attempt < 2:
                time.sleep(13)  # REST SoilGrids limite à ~5 req/min
    if j is None:
        return None
    vals: dict[str, list[float]] = {}
    for layer in j.get("properties", {}).get("layers", []):
        name = layer.get("name")
        dvals = []
        for d in layer.get("depths", []):
            mv = d.get("values", {}).get("mean")
            if mv is not None:
                dvals.append(float(mv))
        if dvals:
            vals[name] = dvals
    if not {"clay", "sand", "silt"} <= set(vals):
        return None
    clay = np.mean(vals["clay"]) / 10.0
    sand = np.mean(vals["sand"]) / 10.0
    silt = np.mean(vals["silt"]) / 10.0
    ph = (np.mean(vals["phh2o"]) / 10.0) if "phh2o" in vals else None
    total = clay + sand + silt
    if total > 0:
        clay, sand, silt = clay * 100 / total, sand * 100 / total, silt * 100 / total
    return describe_soil(sand, silt, clay, ph)


def sample_soil_static(lat: float, lon: float) -> dict | None:
    """Variante 'offline' : lit le sol depuis les couches bakées (.npy) au lieu
    de l'API REST. Plus rapide, mais résolution km. Renvoie describe_soil(...)
    ou None si le bake est absent / hors grille."""
    grids = load_soil_static()
    if grids is None:
        return None
    # index pixel (centres -5.5..10.5 / 51.5..41.0)
    col = int(round((lon - (-5.5)) / GRID_RES))
    row = int(round((51.5 - lat) / GRID_RES))
    if not (0 <= row < GRID_H and 0 <= col < GRID_W):
        return None
    return describe_soil(grids["sand"][row, col], grids["silt"][row, col],
                         grids["clay"][row, col], grids["ph"][row, col])


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "bake":
        print("Baking SoilGrids static layers over France grid…")
        g = build_soil_static(force=True)
        if g is None:
            print("  WCS unreachable — no layers built.")
            sys.exit(1)
        for k, a in g.items():
            v = a[~np.isnan(a)]
            print(f"  {k:5s} shape={a.shape} valid={v.size} "
                  f"min={v.min():.1f} mean={v.mean():.1f} max={v.max():.1f}")
    else:
        lat, lon = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 else (45.5, 4.5)
        print(f"soil_at_point({lat},{lon}) =", soil_at_point(lat, lon))
