"""Analyse d'un point + statut des spots — extrait de champi_core (iso-comportement)."""

from __future__ import annotations

import datetime

import numpy as np

from sporia.config import settings
from sporia.domain.species import MUSHROOMS
from sporia.domain.suitability import (
    PROPICE_MIN,
    PROPICE_PCT,
    RADAR_VMAX,
    _ph_match,
    _radar_label,
    mushroom_suitability,
)
from sporia.enrich import forest as mmap
from sporia.enrich import fruiting_live
from sporia.enrich import soil_static as soil_data
from sporia.enrich import terrain as terrain_data
from sporia.geo.rasters import sample_raster
from sporia.overlays.fruiting import fruiting_models
from sporia.overlays.radar import _radar_species_params
from sporia.places import available_dates, find_commune_at

DATA_DIR = settings.output_tiff_dir

MONTHS_FR = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]


def spots_status(spots, ref_date: str | None = None, selected: list[str] | None = None):
    """Pour une liste de spots [{lat, lon, …}], renvoie le statut courant en
    échantillonnant UNE seule fois la grille radar (habitat × pousse du jour) sur
    la sélection d'espèces du compte. Chaque spot reçoit {score, score_pct, propice,
    date}. Rapide : la grille radar repose sur des couches/scores bakés (cache .npy)."""
    served = set(fruiting_models())
    sel = [s for s in (selected or [m["latin"] for m in MUSHROOMS]) if s in served]
    grid, used, date_iso = fruiting_live.radar(sel, ref_date, params=_radar_species_params())

    out = []
    for sp in spots:
        score = score_pct = None
        if grid is not None:
            row = int(round((fruiting_live.LAT0 - float(sp["lat"])) / fruiting_live.RES))
            col = int(round((float(sp["lon"]) - fruiting_live.LON0) / fruiting_live.RES))
            if 0 <= row < grid.shape[0] and 0 <= col < grid.shape[1]:
                val = grid[row, col]
                if np.isfinite(val):
                    score = float(val)
                    score_pct = int(max(0, min(100, round(100.0 * score / RADAR_VMAX))))
        propice = (
            score is not None
            and score >= PROPICE_MIN
            and score_pct is not None
            and score_pct >= PROPICE_PCT
        )
        out.append(
            {**sp, "score": score, "score_pct": score_pct, "propice": propice, "date": date_iso}
        )
    return out


def _latest_soil_point(prefix: str, ref_date_str: str, lat: float, lon: float):
    """Échantillonne le raster sol PREFIX_*.tif (SM/TS) le plus récent ≤ ref_date
    au point (lat, lon). Le sol n'est rafraîchi qu'~1×/jour → tolérance de date."""
    ref = datetime.datetime.strptime(ref_date_str, "%Y%m%d").date()
    best = None
    for f in DATA_DIR.glob(f"{prefix}_*.tif"):
        try:
            d = datetime.datetime.strptime(f.stem.split("_")[-1], "%Y%m%d").date()
        except Exception:
            continue
        if d <= ref and (best is None or d > best[0]):
            best = (d, f)
    return sample_raster(best[1], lon, lat) if best else None


def analyze_point_weather(lat, lon, ref_date_str, available_date_strs, lookback=20):
    """Synthèse météo + état du sol au point. Pluie 7/14 j, jours depuis pluie et T° air
    récente sont tirés de la MÊME grille Open-Meteo que le radar
    (fruiting_live.recent_temporal_grid, en cache) → fiche et radar COHÉRENTS, et
    instantané (aucun appel réseau). Repli sur les rasters RR/T si la grille manque.
    Humidité/T° du sol = rasters SM/TS du jour."""
    ref = datetime.datetime.strptime(ref_date_str, "%Y%m%d").date()

    rain7 = rain14 = days_since_rain = temp_mean = None
    g = None
    try:
        g = fruiting_live.recent_temporal_grid(ref.isoformat())
    except Exception:
        g = None
    if g is not None:
        row = int(round((fruiting_live.LAT0 - lat) / fruiting_live.RES))
        col = int(round((lon - fruiting_live.LON0) / fruiting_live.RES))
        if 0 <= row < fruiting_live.GRID_H and 0 <= col < fruiting_live.GRID_W:

            def _samp(name):
                arr = g.get(name)
                if arr is None:
                    return None
                v = float(arr[row, col])
                return v if np.isfinite(v) else None

            rain7, rain14, temp_mean = _samp("rain7"), _samp("rain14"), _samp("tmean14")
            dsr = _samp("days_since_rain")
            days_since_rain = int(round(dsr)) if dsr is not None else None

    n_days = fruiting_live.WIN
    if rain7 is None and rain14 is None and temp_mean is None:  # repli rasters
        recs = []
        for ds in available_date_strs:
            d = datetime.datetime.strptime(ds, "%Y%m%d").date()
            if 0 <= (ref - d).days <= lookback:
                recs.append(
                    (
                        d,
                        sample_raster(DATA_DIR / f"RR_{ds}.tif", lon, lat),
                        sample_raster(DATA_DIR / f"T_{ds}.tif", lon, lat),
                    )
                )
        rain7 = sum(rr for d, rr, t in recs if rr is not None and (ref - d).days <= 7)
        rain14 = sum(rr for d, rr, t in recs if rr is not None and (ref - d).days <= 14)
        for d, rr, _t in sorted(recs, key=lambda r: r[0], reverse=True):
            if rr is not None and rr >= 8.0:
                days_since_rain = (ref - d).days
                break
        temps = [t for d, rr, t in recs if t is not None and (ref - d).days <= 7]
        temp_mean = float(np.mean(temps)) if temps else None
        n_days = len(recs)

    soil_moisture = _latest_soil_point("SM", ref_date_str, lat, lon)
    soil_temp = _latest_soil_point("TS", ref_date_str, lat, lon)
    return {
        "month": ref.month,
        "rain7": rain7,
        "rain14": rain14,
        "days_since_rain": days_since_rain,
        "temp_mean": temp_mean,
        "soil_moisture": soil_moisture,
        "soil_temp": soil_temp,
        "n_days": n_days,
    }


def point_report(lat: float, lon: float, ref_date: str, selected: list[str] | None = None):
    """Rapport complet d'un point : commune, météo, sol (texture/pH/humidité/T°),
    relief (altitude/exposition), essence forestière et classement des champignons.
    `selected` = noms latins choisis par l'utilisateur → marque chaque espèce."""
    dates = [d.strftime("%Y%m%d") for d in available_dates()]
    comm = find_commune_at(lat, lon)
    comm_name = str(comm.get("nom_com", "")) if comm is not None else ""
    rr = sample_raster(DATA_DIR / f"RR_{ref_date}.tif", lon, lat)
    t = sample_raster(DATA_DIR / f"T_{ref_date}.tif", lon, lat)
    w = analyze_point_weather(lat, lon, ref_date, dates)

    # Sol : couches SoilGrids bakées (rapide, hors-ligne, couvre toutes les terres).
    # Pas de repli REST dans le chemin requête (lent + rate-limité) ; un sol absent
    # (mer/urbain sans donnée) s'affiche simplement comme « non disponible ».
    soil = soil_data.sample_soil_static(lat, lon)
    # Relief : grille altitude/exposition bakée (instantané, hors-ligne). On évite
    # l'appel IGN RGE ALTI par point (146–2400 ms !) sur le chemin critique du clic ;
    # le baké (même source IGN, maille ~1 km) suffit largement pour la fiche.
    terrain = terrain_data.sample_terrain_static(lat, lon)

    # Famille d'hôte : lue dans les rasters bakés (instantané, aucun appel réseau).
    # Le libellé d'essence précis (tfv) est fourni à la demande par /api/forest (WMS).
    forest = mmap.family_at_point(round(lat, 4), round(lon, 4))
    family = forest.get("family") if forest else None
    sel = set(selected) if selected else None

    # On ne liste que les espèces réellement modélisées/servies (cf. fruiting_models) :
    # une espèce sans modèle affiché (p.ex. la morille) n'apparaît pas dans la fiche.
    served = set(fruiting_models())

    params_all = _radar_species_params()
    ref_iso = datetime.datetime.strptime(ref_date, "%Y%m%d").date().isoformat()
    items = []
    for m in MUSHROOMS:
        if m["latin"] not in served:
            continue
        in_season = w["month"] in m["months"]
        hm = mmap.host_match(m.get("latin", ""), family)
        phm = _ph_match(soil.get("ph") if soil else None, m.get("ph_opt", (4.0, 8.5)))
        score_pct = None
        if not in_season:
            label, level = ("Hors saison", "off")
        else:
            # Verdict = valeur radar (habitat × pousse) au point, identique à la carte/aux spots.
            score, _d = fruiting_live.blended_at_point(
                m["latin"], lat, lon, ref_iso, params_all.get(m["latin"])
            )
            if score is not None:
                score_pct = int(max(0, min(100, round(100.0 * score / RADAR_VMAX))))
                label, level = _radar_label(score, score_pct, True)
            else:
                # Repli (pré-score du jour non baké, p.ex. en dev) : ancienne logique météo.
                label, level, _prio, _phm = mushroom_suitability(m, w, soil, terrain)
        items.append(
            {
                "nom": m["nom"],
                "latin": m["latin"],
                "color": m["color"],
                "months": sorted(m["months"]),
                "t_min": m["t_min"],
                "t_max": m["t_max"],
                "rain_lag": list(m["rain_lag"]),
                "habitat": m["habitat"],
                "ph_opt": list(m["ph_opt"]),
                "soil_pref": m.get("soil_pref", ""),
                "label": label,
                "level": level,
                "score_pct": score_pct,
                "host": hm,
                "soil_ph": phm,
                "selected": (sel is None) or (m["latin"] in sel),
                "_rank": (0 if in_season else 1, -(score_pct if score_pct is not None else -1)),
            }
        )
    items.sort(key=lambda e: (e["_rank"], e["nom"]))
    for it in items:
        it.pop("_rank", None)

    return {
        "lat": lat,
        "lon": lon,
        "commune": comm_name,
        "month": MONTHS_FR[w["month"] - 1],
        "rr": rr,
        "t": t,
        "rain7": w["rain7"],
        "rain14": w["rain14"],
        "days_since_rain": w["days_since_rain"],
        "temp_mean": w["temp_mean"],
        "soil_moisture": w["soil_moisture"],
        "soil_temp": w["soil_temp"],
        "n_days": w["n_days"],
        "soil": soil,
        "terrain": terrain,
        "forest": forest,
        "family": family,
        "mushrooms": items,
    }
