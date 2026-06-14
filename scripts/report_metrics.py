#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Récapitulatif des métriques de validation par espèce, relu depuis les logs de retrain.

Trois colonnes (selon disponibilité) :
  • HABITAT (SDM, le « où »)            ← data/cache/_retrain_sdm.log (tableau récap)
  • FRUCTIFICATION (le « quand »)       ← data/cache/_retrain_172.log (+ _pleurotus.log)
  • RADAR combiné habitat×(0,30+0,70·pousse) ← data/cache/_eval_radar.log (scripts/eval_radar.py)

AUC = 0,5 hasard / 1 parfait ; Boyce = ~0 hasard / 1 parfait (presence-only).
Usage : python scripts/report_metrics.py
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import champi_core as core

CACHE = Path("data/cache")
NOMS = {m["latin"]: m["nom"] for m in core.MUSHROOMS}
NOM_SET = set(NOMS.values())


def _read(p):
    f = CACHE / p
    return f.read_text(encoding="utf-8") if f.exists() else ""


def parse_habitat():
    """Tableau récap train_sdm : 'Latin binom   présence   AUC   Boyce'."""
    out = {}
    for line in _read("_retrain_sdm.log").splitlines():
        m = re.match(r"\s*([A-Z][a-zéèA-Za-z]+ [a-z]+)\s+\d+\s+([01]\.\d{3})\s+(-?[01]\.\d{3})\s*$", line.rstrip())
        if m and m.group(1) in NOMS:
            out[m.group(1)] = (float(m.group(2)), float(m.group(3)))
    return out


def parse_fruiting():
    """Logs fructification : en-tête '----- [i/n] Latin -----' ou 'train_fruiting.py \"Latin\"',
    suivi de 'AUC = .. Boyce = ..'."""
    out = {}
    for text in (_read("_retrain_172.log"), _read("_pleurotus.log")):
        cur = None                                 # reset par fichier (sinon fuite de cur)
        for line in text.splitlines():
            h = (re.search(r"=====\s*(?:\[\d+/\d+\]\s*)?([A-Z][a-zéè]+ [a-z]+)", line)
                 or re.search(r'train_fruiting\.py "([^"]+)"', line)
                 or re.search(r"«\s*([A-Z][a-zéè]+ [a-z]+)\s*»", line))   # ligne « Latin » (log Pleurotus)
            if h and h.group(1) in NOMS:
                cur = h.group(1)
            m = re.search(r"AUC\s*=\s*([0-9.]+)\s+Boyce\s*=\s*(-?[0-9.]+)", line)
            if m and cur:
                out[cur] = (float(m.group(1)), float(m.group(2)))
    return out


# Formule du radar servie : habitat × (HAB_FLOOR + (1-HAB_FLOOR)·pousse).
HAB_FLOOR = 0.30


def combine(hab, fru):
    """Applique la formule du radar aux métriques des deux modèles, par espèce.
    NB : combinaison ARITHMÉTIQUE des indices (pas une re-validation) — donne un ordre
    de grandeur du score combiné ; mécaniquement ≤ habitat (×<1)."""
    out = {}
    for sp in set(hab) & set(fru):
        (ah, bh), (af, bf) = hab[sp], fru[sp]
        f = lambda h, p: h * (HAB_FLOOR + (1 - HAB_FLOOR) * p)
        out[sp] = (f(ah, af), f(bh, bf))
    return out


def main():
    hab, fru = parse_habitat(), parse_fruiting()
    rad = combine(hab, fru)
    excl = getattr(core, "EXCLUDED_FROM_MODELING", set())
    species = [m["latin"] for m in core.MUSHROOMS if m["latin"] not in excl]
    species.sort(key=lambda s: -(hab.get(s, (0, 0))[1]))   # tri par Boyce habitat décroissant

    has_rad = bool(rad)
    head = f"{'Espèce':24s} | {'AUC hab':>7s} {'Boyce hab':>9s} | {'AUC fr':>6s} {'Boyce fr':>8s}"
    if has_rad:
        head += f" | {'AUC rad':>7s} {'Boyce rad':>9s}"
    print("\n" + head)
    print("-" * len(head))

    cols = {"ah": [], "bh": [], "af": [], "bf": [], "ar": [], "br": []}

    def cell(d, sp, w1, w2):
        v = d.get(sp)
        return (f"{v[0]:{w1}.3f} {v[1]:{w2}.3f}" if v else f"{'—':>{w1}s} {'—':>{w2}s}"), v

    for sp in species:
        hs, hv = cell(hab, sp, 7, 9)
        fs, fv = cell(fru, sp, 6, 8)
        row = f"{NOMS.get(sp, sp):24s} | {hs} | {fs}"
        if has_rad:
            rs, rv = cell(rad, sp, 7, 9)
            row += f" | {rs}"
            if rv: cols["ar"].append(rv[0]); cols["br"].append(rv[1])
        if hv: cols["ah"].append(hv[0]); cols["bh"].append(hv[1])
        if fv: cols["af"].append(fv[0]); cols["bf"].append(fv[1])
        print(row)

    mean = lambda x: (sum(x) / len(x)) if x else float("nan")
    print("-" * len(head))
    line = f"{'MOYENNE':24s} | {mean(cols['ah']):7.3f} {mean(cols['bh']):9.3f} | {mean(cols['af']):6.3f} {mean(cols['bf']):8.3f}"
    if has_rad:
        line += f" | {mean(cols['ar']):7.3f} {mean(cols['br']):9.3f}"
    print(line)
    print("\nAUC 0,5=hasard·1=parfait | Boyce ~0=hasard·1=parfait.")
    print("rad = habitat × (0,30 + 0,70 × pousse) appliqué aux indices (combinaison arithmétique,"
          " ≤ habitat car ×<1 ; pas une re-validation).")


if __name__ == "__main__":
    main()
