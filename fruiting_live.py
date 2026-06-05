# -*- coding: utf-8 -*-
"""
Scoring « POUSSE EN CE MOMENT » (productionisation du point #4, fructification).

Applique un modèle de fructification (scripts/train_fruiting.py → data/cache/
fruiting_<latin>.pkl) à la météo des ~21 derniers jours pour produire une carte
nationale de probabilité « c'est le bon moment ».

La météo récente n'étant pas (encore) accumulée en rasters par le pipeline, on la
récupère à la demande sur Open-Meteo (forecast API, past_days=21, bulk multi-points
sur une grille grossière) → mêmes 6 variables que l'entraînement, puis IDW vers la
grille 0.01°. Le résultat météo est mis en cache par date (wx_recent_<date>.npz),
partagé entre espèces. Les couches statiques (forêt/sol/relief) sont les .npy bakés.

N'IMPORTE PAS champi_core (anti-circulaire) : le masquage France et le rendu PNG
sont faits par champi_core via _render_grid_overlay.
"""
from __future__ import annotations
import datetime as dt
import pickle
import time
from pathlib import Path

import numpy as np
import requests

import mushroom_map as mmap
import soil_data
import terrain_data
from interpret_day import idw

GRID_H, GRID_W, RES = 1051, 1601, 0.01
LON0, LAT0 = -5.5, 51.5
BBOX = (-5.5, 10.5, 41.0, 51.5)
FORECAST = "https://api.open-meteo.com/v1/forecast"
CACHE = Path("data/cache")
WIN = 21

STATIC = ["forest_density", "ph", "clay", "sand", "silt", "altitude", "slope", "northness"]
TEMPORAL = ["rain7", "rain14", "rain21", "tmean14", "sm_mean", "days_since_rain"]


# Espèces NON servies dans le calque « pousse en ce moment » : modèle d'HABITAT
# trop faible/inversé (Boyce < 0.2) pour une carte spatiale fiable — le « où »
# serait ≤ hasard, même si le « quand » (météo) est bon. Gardées au catalogue/
# guide + SDM. (Décision : ne servir que solide+modeste, 2026-06-01.)
_HIDDEN_FRUITING = {
    # Seule la morille reste non servie : habitat Boyce -0.40 (inversé/trompeur),
    # non modélisable même après filtre anti-urbain et distance-eau.
    # Depuis l'ajout de l'arbre-hôte (host_*, par guilde), TOUTES les autres espèces
    # ont un Boyce habitat >= 0.2 — dont trompette de la mort 0.30, Lepista 0.67,
    # Lactarius 0.36 (jadis masquées) → désormais servies.
    "Morchella esculenta",
}


def available_models() -> list[str]:
    """Espèces (nom latin) avec un modèle de fructification baké ET dont l'habitat
    est assez fiable pour servir une carte spatiale (cf. _HIDDEN_FRUITING)."""
    out = []
    for p in sorted(CACHE.glob("fruiting_*.pkl")):
        sp = p.stem[len("fruiting_"):].replace("_", " ")
        if sp not in _HIDDEN_FRUITING:
            out.append(sp)
    return out


def _static_layers():
    dens = mmap.load_forest_density()
    soil = soil_data.load_soil_static()
    terr = terrain_data.load_terrain_static()
    if dens is None or soil is None or terr is None:
        return None
    layers = {
        "forest_density": dens.astype(np.float32),
        "ph": soil["ph"], "clay": soil["clay"], "sand": soil["sand"], "silt": soil["silt"],
        "altitude": terr["altitude"], "slope": terr["slope"], "northness": terr["northness"],
    }
    # Couches bakées supplémentaires (WorldClim clim_*, occupation du sol lc_*) pour
    # matcher les features des modèles enrichis. On ne récupère PAS host_* ici (NaN
    # hors-forêt + logique par guilde) — l'habitat-hôte est déjà porté par le SDM.
    # Inoffensif pour les anciens modèles : score_species ne lit que obj["features"].
    for f in sorted(CACHE.glob("clim_*.npy")) + sorted(CACHE.glob("lc_*.npy")):
        try:
            arr = np.load(f)
            if arr.shape == (GRID_H, GRID_W):
                layers[f.stem] = arr.astype(np.float32)
        except Exception:
            pass
    return layers


def _feats_from_daily(d) -> list[float] | None:
    """6 variables météo antécédentes depuis le bloc `daily` d'un point Open-Meteo.
    Identique à train_fruiting.antecedent_wx (mêmes fenêtres / seuils / ordre)."""
    pr = np.array([x if x is not None else np.nan for x in d.get("precipitation_sum", [])], float)
    tm = np.array([x if x is not None else np.nan for x in d.get("temperature_2m_mean", [])], float)
    sm = np.array([x if x is not None else np.nan for x in d.get("soil_moisture_0_to_7cm_mean", [])], float)
    if pr.size < WIN:
        return None
    dsr = WIN
    for k in range(len(pr) - 1, -1, -1):
        if np.isfinite(pr[k]) and pr[k] >= 8.0:
            dsr = (len(pr) - 1) - k
            break
    return [float(np.nansum(pr[-7:])), float(np.nansum(pr[-14:])), float(np.nansum(pr)),
            float(np.nanmean(tm[-14:])), float(np.nanmean(sm[-7:])), float(dsr)]


def _fetch_recent_points(step=0.3, batch=150):
    """Grille grossière sur la bbox → météo récente Open-Meteo (bulk).
    Renvoie (points Nx2 lon/lat, values Nx6 dans l'ordre TEMPORAL)."""
    lons = np.arange(BBOX[0], BBOX[1] + 1e-9, step)
    lats = np.arange(BBOX[2], BBOX[3] + 1e-9, step)
    LON, LAT = np.meshgrid(lons, lats)
    pts = np.vstack([LON.ravel(), LAT.ravel()]).T
    P, V = [], []
    for i in range(0, len(pts), batch):
        chunk = pts[i:i + batch]
        for attempt in range(4):
            try:
                r = requests.get(FORECAST, params={
                    "latitude": ",".join(f"{la:.3f}" for la in chunk[:, 1]),
                    "longitude": ",".join(f"{lo:.3f}" for lo in chunk[:, 0]),
                    "daily": "precipitation_sum,temperature_2m_mean,soil_moisture_0_to_7cm_mean",
                    "past_days": WIN, "forecast_days": 1, "timezone": "UTC"}, timeout=60)
                if r.status_code == 429:
                    time.sleep(12 * (attempt + 1)); continue
                r.raise_for_status()
                j = r.json()
                break
            except Exception:
                if attempt == 3:
                    j = None
                time.sleep(4 * (attempt + 1))
        if not j:
            continue
        recs = j if isinstance(j, list) else [j]
        for pt, rec in zip(chunk, recs):
            f = _feats_from_daily(rec.get("daily", {}))
            if f is not None:
                P.append(pt); V.append(f)
        time.sleep(0.3)
    return np.array(P, float), np.array(V, float)


_wx_mem_cache: dict[str, dict] = {}


def recent_temporal_grid(date_str: str | None = None, step=0.3):
    """Grilles 0.01° des 6 variables météo récentes (IDW depuis la grille grossière),
    mises en cache sur disque (npz) ET en mémoire par date — la lecture du npz (~40 Mo)
    coûte ~200 ms, donc on garde le dict décompressé en RAM pour les appels suivants
    (point_report, radar, spots restent instantanés). Renvoie dict {feat: grid2d} ou None."""
    today = date_str or dt.date.today().isoformat()
    if today in _wx_mem_cache:
        return _wx_mem_cache[today]
    cache = CACHE / f"wx_recent_{today.replace('-', '')}.npz"
    if cache.exists():
        z = np.load(cache)
        grids = {k: z[k] for k in TEMPORAL}
        _wx_mem_cache[today] = grids
        return grids
    P, V = _fetch_recent_points(step=step)
    if len(P) < 10:
        return None
    lonv = (LON0 + np.arange(GRID_W) * RES)
    latv = (LAT0 - np.arange(GRID_H) * RES)
    LON, LAT = np.meshgrid(lonv, latv)
    xi = np.vstack([LON.ravel(), LAT.ravel()]).T
    grids = {}
    for j, name in enumerate(TEMPORAL):
        g = idw(P, V[:, j], xi, power=2.0, k=8).reshape(GRID_H, GRID_W).astype(np.float32)
        grids[name] = g
    np.savez_compressed(cache, **grids)
    _wx_mem_cache[today] = grids
    return grids


def score_species(species: str, date_str: str | None = None):
    """Carte de probabilité de fructification (grille 0.01°, NaN hors données).
    Renvoie (grid2d, date_iso) ou (None, date_iso)."""
    today = date_str or dt.date.today().isoformat()
    pkl = CACHE / f"fruiting_{species.replace(' ', '_')}.pkl"
    if not pkl.exists():
        return None, today
    out_npy = CACHE / f"fruiting_score_{species.replace(' ', '_')}_{today.replace('-', '')}.npy"
    if out_npy.exists():                                   # cache du jour (prewarm) → instantané
        return np.load(out_npy), today
    obj = pickle.loads(pkl.read_bytes())
    model, feats = obj["model"], obj["features"]
    stat = _static_layers()
    temp = recent_temporal_grid(today)
    if stat is None or temp is None:
        return None, today
    layers = {**stat, **temp}
    cols = np.stack([layers[f].ravel() for f in feats], axis=1)   # (N, n_feats) dans l'ordre du modèle
    ok = np.isfinite(cols).all(axis=1)
    proba = np.full(GRID_H * GRID_W, np.nan, np.float32)
    if ok.any():
        proba[ok] = model.predict_proba(cols[ok])[:, 1].astype(np.float32)
    grid = proba.reshape(GRID_H, GRID_W)
    np.save(out_npy, grid)
    return grid, today


# === « Radar à champignons » : blend OÙ (habitat, SDM avec arbre-hôte) × QUAND (météo) ===
HAB_FLOOR = 0.30   # part d'habitat affichée hors-saison (la carte montre toujours le bon habitat,
                   # puis « s'illumine » quand les conditions de pousse du moment sont réunies)

# ---- Modulation « fenêtre de pousse » (récence pluie + cumul récent + température) ----
# Le modèle ML sous-pondère la récence : il peut « s'illuminer » sur une grosse pluie
# vieille de 3 semaines. On encode donc la règle mycologique classique — la
# fructification suit une bonne pluie de ~4 à 15 jours, à température douce — comme un
# facteur ∈ [~0.2, 1] qui multiplie la proba de pousse. Valeurs grand public (non
# spécifiques à l'espèce ; le modèle/SDM portent déjà la nuance par espèce).
# Valeurs par défaut (si aucun paramètre d'espèce fourni) — mycologie « grand public ».
DEF_LAG = (4.0, 15.0)   # fenêtre post-pluie (jours)
DEF_RAIN_MIN = 20.0     # mm sur 14 j pour une humidité récente « pleine »
DEF_TEMP = (8.0, 24.0)  # plage de température douce (°C)
_timing_cache: dict[tuple, np.ndarray] = {}


def _recency_factor(dsr, lo=4.0, hi=15.0):
    """Récence de la pluie : pleine dans la fenêtre [lo, hi] (jours post-pluie de
    l'espèce). Un peu basse si trop récent (< lo), décroît si ça sèche (> hi →
    ~0.2 à +10 j). NaN/inconnu → 0.3."""
    f = np.ones_like(dsr, dtype=np.float32)
    f = np.where(dsr < lo, 0.6 + 0.4 * np.clip(dsr / max(lo, 1e-6), 0.0, 1.0), f)
    f = np.where(dsr > hi, 1.0 - 0.08 * (dsr - hi), f)
    f = np.where(np.isfinite(dsr), f, 0.3)
    return np.clip(f, 0.2, 1.0).astype(np.float32)


def _temp_factor(t, tmin=8.0, tmax=24.0):
    """Température : pleine dans [tmin, tmax] de l'espèce, décroît à ~0.3 vers ±6 °C."""
    f = np.ones_like(t, dtype=np.float32)
    f = np.where(t < tmin, 1.0 - (tmin - t) / 6.0 * 0.7, f)
    f = np.where(t > tmax, 1.0 - (t - tmax) / 6.0 * 0.7, f)
    f = np.where(np.isfinite(t), f, 0.5)
    return np.clip(f, 0.3, 1.0).astype(np.float32)


def timing_grid(params: dict | None = None, date_str: str | None = None):
    """Facteur « bon moment » (0.2–1) par maille = récence pluie × cumul 14 j × T°,
    PARAMÉTRÉ PAR ESPÈCE (rain_lag / rain_min / t_min,t_max issus de MUSHROOMS, passés
    par champi_core). Mis en cache par (date, params). None si météo absente."""
    p = params or {}
    lo, hi = p.get("rain_lag", DEF_LAG)
    rmin = float(p.get("rain_min", DEF_RAIN_MIN))
    tmin, tmax = p.get("t_min", DEF_TEMP[0]), p.get("t_max", DEF_TEMP[1])
    today = date_str or dt.date.today().isoformat()
    key = (today, float(lo), float(hi), rmin, float(tmin), float(tmax))
    if key in _timing_cache:
        return _timing_cache[key]
    g = recent_temporal_grid(today)
    if g is None:
        return None
    rec = _recency_factor(g["days_since_rain"], float(lo), float(hi))
    amt = np.clip(g["rain14"] / max(rmin, 1e-6), 0.3, 1.0).astype(np.float32)
    tmp = _temp_factor(g["tmean14"], float(tmin), float(tmax))
    out = (rec * amt * tmp).astype(np.float32)
    _timing_cache[key] = out
    return out


def blended_species(species: str, date_str: str | None = None, params: dict | None = None):
    """Carte « habitat × moment » d'une espèce : SDM d'habitat (sdm_<latin>.npy, enrichi
    arbre-hôte) modulé par la probabilité de pousse du jour, elle-même tempérée par la
    fenêtre de pousse PROPRE À L'ESPÈCE (délai post-pluie / cumul / T°). NaN hors habitat."""
    fruit, date = score_species(species, date_str)
    if fruit is None:
        return None, date
    tf = timing_grid(params, date_str)
    fruit_eff = np.nan_to_num(fruit, nan=0.0)
    if tf is not None:
        fruit_eff = np.clip(fruit_eff * tf, 0.0, 1.0)
    sdm = CACHE / f"sdm_{species.replace(' ', '_')}.npy"
    if sdm.exists():
        hab = np.load(sdm)
        blended = hab * (HAB_FLOOR + (1.0 - HAB_FLOOR) * fruit_eff)
    else:
        blended = fruit_eff
    return blended.astype(np.float32), date


def radar(species_list, date_str: str | None = None, params: dict | None = None):
    """Carte agrégée (max) sur les espèces demandées → (grid2d, espèces_utilisées, date).
    `params` = {latin: {rain_lag, rain_min, t_min, t_max}} (fourni par champi_core depuis
    MUSHROOMS) pour moduler la fenêtre de pousse PAR ESPÈCE."""
    grids, used, date = [], [], (date_str or dt.date.today().isoformat())
    params = params or {}
    for sp in species_list or []:
        if sp in _HIDDEN_FRUITING:
            continue
        g, date = blended_species(sp, date_str, params.get(sp))
        if g is not None:
            grids.append(g); used.append(sp)
    if not grids:
        return None, [], date
    import warnings
    with warnings.catch_warnings():                       # cellules tout-NaN → NaN (normal)
        warnings.simplefilter("ignore", RuntimeWarning)
        agg = np.nanmax(np.stack(grids), axis=0).astype(np.float32)
    return agg, used, date


def prewarm(date_str: str | None = None):
    """Pré-chauffe le cache météo du jour + pré-score chaque modèle (pour que
    l'endpoint /api/fruiting réponde vite). Appelé par le scheduler."""
    import time
    t0 = time.time()
    grids = recent_temporal_grid(date_str)
    if grids is None:
        print("prewarm : météo récente indisponible", flush=True)
        return 1
    print(f"prewarm : grille météo récente prête ({time.time()-t0:.0f}s)", flush=True)
    for sp in available_models():
        t1 = time.time()
        grid, d = score_species(sp, date_str)
        ok = grid is not None
        print(f"prewarm : {sp} {'OK' if ok else 'ÉCHEC'} ({time.time()-t1:.0f}s)", flush=True)
    return 0


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "prewarm":
        sys.exit(prewarm(sys.argv[2] if len(sys.argv) > 2 else None))
    sp = sys.argv[1] if len(sys.argv) > 1 else "Boletus edulis"
    g, d = score_species(sp)
    if g is None:
        print(f"{sp} : pas de modèle / météo indispo")
    else:
        print(f"{sp} @ {d} : {int(np.isfinite(g).sum())} cellules, "
              f"max {np.nanmax(g):.2f}")
