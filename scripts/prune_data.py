#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Purge des données BRUTES / intermédiaires pour que l'outil ne grossisse pas.

Principe : on garde une fenêtre récente, calculée RELATIVEMENT à la donnée la plus
récente de chaque dossier (jamais par rapport à « aujourd'hui ») → on ne vide jamais
par erreur si le pipeline a été à l'arrêt.

Ne touche JAMAIS : output/tiff récents (l'appli en a besoin), les couches dérivées
(clim_/lc_/host_/soil_/terrain_/altitude/sdm_/fruiting_*.npy/pkl), les .gpkg/.csv de
référence. Supprime : tuiles AROME brutes, radar H5 bruts, daily déjà interprétés
anciens, rasters output trop vieux, et la zip WorldClim une fois extraite.

Usage : python scripts/prune_data.py [--dry-run]
"""
from __future__ import annotations
import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATE_RE = re.compile(r"(\d{4})-?(\d{2})-?(\d{2})")

# (dossier, motifs, jours conservés relativement au plus récent du dossier)
RULES = [
    ("data/arome_wcs", ("*.tif", "*.idx"), 2),    # tuiles AROME brutes (NPZ cache les remplace)
    ("data/radar_h5",  ("*.h5", "*"),      3),     # radar 5-min brut (radar_cumul en garde le résultat)
    ("data/daily",     ("arome_*.csv", "radar_cumul_*.nc"), 35),  # bruts journaliers déjà interprétés
    ("output/tiff",    ("RR_*.tif", "T_*.tif", "SM_*.tif", "TS_*.tif"), 45),  # rasters appli (fenêtre large)
]


def file_day(p: Path):
    m = DATE_RE.search(p.stem)
    if m:
        try:
            import datetime as dt
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def prune_dir(rel, patterns, keep_days, dry):
    d = ROOT / rel
    if not d.exists():
        return 0, 0
    files = []
    for pat in patterns:
        files += [f for f in d.glob(pat) if f.is_file()]
    files = list(dict.fromkeys(files))
    if not files:
        return 0, 0
    import datetime as dt
    # ancre = jour le plus récent trouvé (sinon mtime le plus récent)
    days = [file_day(f) for f in files]
    dated = [x for x in days if x]
    if dated:
        anchor = max(dated)
        cutoff = anchor - dt.timedelta(days=keep_days)
        def too_old(f, fd): return fd is not None and fd < cutoff
    else:
        anchor_m = max(f.stat().st_mtime for f in files)
        cutoff_m = anchor_m - keep_days * 86400
        def too_old(f, fd): return f.stat().st_mtime < cutoff_m
    n, sz = 0, 0
    for f, fd in zip(files, days):
        old = too_old(f, fd) if dated else too_old(f, None)
        if old:
            sz += f.stat().st_size; n += 1
            if not dry:
                f.unlink(missing_ok=True)
    print(f"  {rel:18s} : {n} fichiers, {sz/1e6:.0f} Mo "
          f"({'à supprimer' if dry else 'supprimés'}) — conserve {keep_days} j")
    return n, sz


def prune_worldclim_zip(dry):
    cache = ROOT / "data/cache"
    zip_path = cache / "worldclim" / "wc2.1_2.5m_bio.zip"
    have_clim = list(cache.glob("clim_*.npy"))
    if zip_path.exists() and have_clim:
        sz = zip_path.stat().st_size
        if not dry:
            zip_path.unlink()
        print(f"  worldclim zip      : 1 fichier, {sz/1e6:.0f} Mo "
              f"({'à supprimer' if dry else 'supprimée'}) — {len(have_clim)} clim_*.npy présents")
        return 1, sz
    return 0, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="liste sans supprimer")
    a = ap.parse_args()
    print(f"Purge données brutes/intermédiaires{' (DRY-RUN)' if a.dry_run else ''} :")
    tot_n, tot_sz = 0, 0
    for rel, pats, keep in RULES:
        n, sz = prune_dir(rel, pats, keep, a.dry_run)
        tot_n += n; tot_sz += sz
    n, sz = prune_worldclim_zip(a.dry_run)
    tot_n += n; tot_sz += sz
    verb = "libérables" if a.dry_run else "libérés"
    print(f"\nTotal : {tot_n} fichiers, {tot_sz/1e6:.0f} Mo {verb}.")


if __name__ == "__main__":
    main()
