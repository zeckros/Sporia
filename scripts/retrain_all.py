#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Réentraîne TOUS les modèles sur le jeu de prédicteurs enrichi (essence fine BD Forêt,
TWI/TPI/distance-eau, SOC/CEC, lisière, WorldClim bio5/bio17, météo P−ET0 + choc
thermique + fenêtres longues + humidité racinaire).

  1. SDM d'habitat  (train_sdm --all --predict)          → sdm_<latin>.npy
  2. Fructification (train_fruiting par espèce)          → fruiting_<latin>.pkl

Récapitule l'AUC/Boyce par espèce. À lancer depuis la racine du projet, APRÈS que tous
les bakes de couches soient terminés.
Usage : python scripts/retrain_all.py [--skip-sdm] [--skip-fruiting] [--max-pres 250]
"""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import champi_core as core                        # noqa: E402

PY = sys.executable


def run(cmd):
    print(f"\n$ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=str(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-sdm", action="store_true")
    ap.add_argument("--skip-fruiting", action="store_true")
    ap.add_argument("--max-pres", type=int, default=250)
    a = ap.parse_args()

    excl = getattr(core, "EXCLUDED_FROM_MODELING", set())
    species = [m["latin"] for m in core.MUSHROOMS if m["latin"] not in excl]

    if not a.skip_sdm:
        print("=" * 70 + "\n  ÉTAPE 1/2 — SDM d'habitat (toutes espèces)\n" + "=" * 70)
        run([PY, "scripts/train_sdm.py", "--all", "--predict"])

    if not a.skip_fruiting:
        print("\n" + "=" * 70 + "\n  ÉTAPE 2/2 — Fructification (par espèce)\n" + "=" * 70)
        for i, sp in enumerate(species, 1):
            print(f"\n----- [{i}/{len(species)}] {sp} -----", flush=True)
            run([PY, "scripts/train_fruiting.py", sp, "--max-pres", str(a.max_pres)])

    print("\nFait. Régénère ensuite les caches du jour : "
          "python -c \"import fruiting_live; fruiting_live.prewarm()\"")


if __name__ == "__main__":
    main()
