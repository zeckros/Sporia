# -*- coding: utf-8 -*-
"""
Features MÉTÉO ANTÉCÉDENTES — source unique de vérité (entraînement ET live).

Avant, le calcul des variables météo était dupliqué entre scripts/train_fruiting.py
(archive ERA5) et fruiting_live.py (forecast Open-Meteo), au risque de diverger.
Ce module centralise : la fenêtre récupérée (LONG), la liste DAILY_VARS demandée à
Open-Meteo, l'ordre canonique TEMPORAL, et la fonction de calcul.

Enrichissements (vs l'ancien jeu de 6 variables) :
  • bilan hydrique P−ET0 (wbal14/wbal30) — l'eau réellement disponible, pas la pluie
    brute (20 mm en juin s'évaporent, pas en octobre) ;
  • choc thermique automnal — amplitude diurne (tamp7) et refroidissement récent
    (tdrop = T° moy. j8-21 − T° moy. 7 derniers jours), déclencheur classique de
    fructification que la seule moyenne tmean14 ne capte pas ;
  • fenêtres longues rain30/rain60 — mémoire du mycélium (un été humide prépare
    l'automne) ;
  • humidité du sol en zone racinaire sm28_mean (7-28 cm), plus représentative que la
    seule surface 0-7 cm (qui sèche vite).
"""
from __future__ import annotations
import numpy as np

# Jours de météo antécédente récupérés (forecast past_days ≤ 92 ; archive : libre).
LONG = 92
RAIN_EVENT = 8.0  # mm/j : seuil « il a vraiment plu » (jours-depuis-pluie)

# Variables daily demandées à Open-Meteo (forecast & archive acceptent les mêmes).
DAILY_VARS = ("precipitation_sum,temperature_2m_mean,temperature_2m_max,"
              "temperature_2m_min,soil_moisture_0_to_7cm_mean,"
              "soil_moisture_7_to_28cm_mean,et0_fao_evapotranspiration")

# Ordre canonique des features temporelles (colonnes du modèle de fructification).
TEMPORAL = ["rain7", "rain14", "rain21", "rain30", "rain60",
            "tmean14", "tamp7", "tdrop",
            "wbal14", "wbal30",
            "sm_mean", "sm28_mean", "days_since_rain"]


def _arr(daily: dict, key: str) -> np.ndarray:
    return np.array([x if x is not None else np.nan for x in daily.get(key, [])], float)


def _nansum(a: np.ndarray, n: int) -> float:
    return float(np.nansum(a[-n:])) if a.size else np.nan


def _nanmean(a: np.ndarray, n: int) -> float:
    s = a[-n:]
    return float(np.nanmean(s)) if s.size and np.isfinite(s).any() else np.nan


def features_from_daily(daily: dict) -> dict | None:
    """Dict {nom: valeur} des features TEMPORAL depuis un bloc `daily` Open-Meteo
    (≥ ~30 j). None si la série est trop courte. Robuste aux None / NaN."""
    pr = _arr(daily, "precipitation_sum")
    tm = _arr(daily, "temperature_2m_mean")
    tmx = _arr(daily, "temperature_2m_max")
    tmn = _arr(daily, "temperature_2m_min")
    sm0 = _arr(daily, "soil_moisture_0_to_7cm_mean")
    sm28 = _arr(daily, "soil_moisture_7_to_28cm_mean")
    et0 = _arr(daily, "et0_fao_evapotranspiration")
    if pr.size < 30:
        return None
    amp = tmx - tmn
    recent = _nanmean(tm, 7)
    prev = _nanmean(tm[:-7], 14)                       # T° moy. des 14 j précédant la dernière semaine
    tdrop = (prev - recent) if (np.isfinite(prev) and np.isfinite(recent)) else 0.0
    dsr = float(LONG)
    for k in range(len(pr) - 1, -1, -1):
        if np.isfinite(pr[k]) and pr[k] >= RAIN_EVENT:
            dsr = float((len(pr) - 1) - k)
            break
    return {
        "rain7": _nansum(pr, 7), "rain14": _nansum(pr, 14), "rain21": _nansum(pr, 21),
        "rain30": _nansum(pr, 30), "rain60": _nansum(pr, 60),
        "tmean14": _nanmean(tm, 14), "tamp7": _nanmean(amp, 7), "tdrop": tdrop,
        "wbal14": _nansum(pr, 14) - _nansum(et0, 14),
        "wbal30": _nansum(pr, 30) - _nansum(et0, 30),
        "sm_mean": _nanmean(sm0, 7), "sm28_mean": _nanmean(sm28, 7),
        "days_since_rain": dsr,
    }


def features_list(daily: dict) -> list[float] | None:
    """Comme features_from_daily mais renvoie une liste dans l'ordre TEMPORAL."""
    d = features_from_daily(daily)
    return None if d is None else [d[k] for k in TEMPORAL]
