"""Modèle d'adéquation à règles (pur, sans I/O) — extrait de champi_core, iso-comportement.

Contient aussi les constantes de domaine partagées : `_ASPECT_W` (pondération saisonnière
d'exposition, ex-mushroom_map) et les seuils du radar (RADAR_VMAX / PROPICE_*)."""

from __future__ import annotations

import numpy as np

# Pondération exposition par mois : >0 favorise les versants nord (frais/humides),
# <0 favorise les versants sud (plus chauds). Été→nord, fin d'automne/hiver→sud.
_ASPECT_W = {
    1: -0.10,
    2: -0.10,
    3: 0.05,
    4: 0.05,
    5: 0.05,
    6: 0.10,
    7: 0.10,
    8: 0.10,
    9: -0.05,
    10: -0.05,
    11: -0.10,
    12: -0.10,
}

# Seuils « propice » du radar. Échelle ABSOLUE (pas le P99 du jour) : en période
# globalement défavorable la carte reste sombre. Volontairement faciles à ajuster.
RADAR_VMAX = 0.60  # valeur radar brute (habitat×moment) correspondant à l'indice 100 %
PROPICE_MIN = 0.30  # garde-fou absolu sur la valeur radar brute
PROPICE_PCT = 70  # % de l'indice (vs RADAR_VMAX) requis pour « propice »


def _ph_match(ph, ph_opt) -> str:
    """'ok' (pH dans la plage), 'mid' (proche), 'no' (inadapté) ou 'unknown'."""
    if ph is None:
        return "unknown"
    lo, hi = ph_opt
    if (lo - 0.3) <= ph <= (hi + 0.3):
        return "ok"
    if (lo - 1.0) <= ph <= (hi + 1.0):
        return "mid"
    return "no"


def _altitude_fit_point(alt, alt_opt):
    """Adéquation altitude scalaire (0.3..1) — même logique que la carte :
    pénalité au-dessus de ~1800 m (limite forestière) + fenêtre par espèce."""
    if alt is None:
        return 1.0
    treeline = 1.0 - min(max((alt - 1800.0) / 600.0, 0.0), 0.6)
    if alt_opt:
        lo, hi = alt_opt
        below = min(max((lo - alt) / 400.0, 0.0), 1.0)
        above = min(max((alt - hi) / 400.0, 0.0), 1.0)
        window = 0.4 + 0.6 * max(0.0, 1.0 - below - above)
    else:
        window = 1.0
    return max(0.3, min(1.0, treeline * window))


def _aspect_fit_point(northness, month):
    """Modulateur exposition scalaire (0.85..1.15) — même logique saisonnière que
    la carte (été → versant nord/frais, automne-hiver → versant sud/chaud)."""
    if northness is None:
        return 1.0
    w = _ASPECT_W.get(month, 0.0)
    return float(np.clip(1.0 + w * northness, 0.85, 1.15))


def mushroom_suitability(m, w, soil=None, terrain=None):
    """Classe l'adéquation d'une espèce au point : saison, T° (air+sol), humidité
    (pluie récente OU sol humide), pH, ALTITUDE et EXPOSITION — cohérent avec le
    modèle de la carte. Renvoie (label, niveau, priorité_tri, ph_match)."""
    if w["month"] not in m["months"]:
        return ("Hors saison", "off", 3, "unknown")

    ta, ts = w.get("temp_mean"), w.get("soil_temp")
    if ta is not None and ts is not None:
        temp = 0.5 * ta + 0.5 * ts
    else:
        temp = ta if ta is not None else ts
    temp_ok = temp is not None and (m["t_min"] - 1) <= temp <= (m["t_max"] + 1)

    lag_lo, lag_hi = m["rain_lag"]
    dsr = w["days_since_rain"]
    rain_ok = (
        dsr is not None and lag_lo <= dsr <= lag_hi and (w.get("rain14") or 0) >= m["rain_min"]
    )
    sm = w.get("soil_moisture")
    moist_ok = rain_ok or (sm is not None and sm >= 0.22)

    ph = soil.get("ph") if soil else None
    phm = _ph_match(ph, m.get("ph_opt", (4.0, 8.5)))
    ph_bad = phm == "no"

    # Relief : altitude (par espèce + limite forestière) et exposition (saisonnière)
    alt = terrain.get("altitude") if terrain else None
    north = terrain.get("northness") if terrain else None
    alt_fit = _altitude_fit_point(alt, m.get("alt_opt"))
    asp_fit = _aspect_fit_point(north, w["month"])
    alt_bad = alt_fit < 0.6
    # tri : meilleure altitude/exposition → priorité plus basse (remonte la liste)
    terr_adj = (1.0 - alt_fit * asp_fit) * 0.6

    if temp_ok and moist_ok and not ph_bad and not alt_bad:
        return ("Favorable", "good", 0.0 + terr_adj, phm)
    if alt_bad and (temp_ok or moist_ok):
        return ("Altitude peu adaptée", "mid", 1.5 + terr_adj, phm)
    if ph_bad and (temp_ok or moist_ok):
        return ("Sol peu adapté", "mid", 1.5 + terr_adj, phm)
    if temp_ok or moist_ok:
        return ("Conditions partielles", "mid", 1.0 + terr_adj, phm)
    return ("Peu probable", "bad", 2.0 + terr_adj, phm)


def _radar_label(score, score_pct, in_season):
    """Libellé + niveau d'une espèce à un point, DÉRIVÉS DE LA VALEUR RADAR
    (habitat × pousse) — même source que la carte et les spots, donc cohérence totale.
    Bandes alignées sur RADAR_VMAX / PROPICE_*."""
    if not in_season:
        return ("Hors saison", "off")
    if score is None or score_pct is None:
        return ("n.d.", "off")
    if score >= PROPICE_MIN and score_pct >= PROPICE_PCT:
        return ("Très propice", "good")
    if score_pct >= 45:
        return ("Favorable", "good")
    if score_pct >= 20:
        return ("Possible", "mid")
    return ("Peu probable", "bad")
