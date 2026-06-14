#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bake des PRÉDICTEURS D'HUMIDITÉ TOPOGRAPHIQUE sur la grille Sporia (axe P1.4).

L'altitude bakée par terrain_data.py est échantillonnée à ~0,1° (≈11 km) puis IDW :
trop lisse pour la micro-topographie qui pilote l'humidité (bas de pente, thalwegs)
— or les champignons aiment justement les fonds frais et humides. Ce script repart
d'un VRAI MNT fin (Copernicus GLO-90, 90 m, AWS open data, sans auth, lu en streaming
/vsicurl) agrégé proprement à la grille 1 km, et en dérive par hydrologie :

  • twi.npy        Topographic Wetness Index = ln(aire drainée / tan(pente)). Élevé dans
                   les bas-fonds convergents (humides), faible sur les croupes (sèches).
  • tpi.npy        Topographic Position Index (altitude − moyenne locale, fenêtre ~5 km) :
                   négatif = vallée/cuvette, positif = crête. Capte les fonds de vallée.
  • dist_water.npy Distance (km) au réseau de drainage dérivé de l'accumulation de flux
                   (proxy « proximité d'un cours d'eau »), sans tirer la BD TOPO entière.
  • slope_dem.npy  Pente (%) issue du MNT fin (plus fidèle que la pente 0,1°).

Hydrologie : remplissage des cuvettes par priority-flood (tas), directions D8 sur le MNT
rempli, accumulation par ordre d'altitude décroissante (O(N)).

Sorties data/cache/*.npy — hookées par train_sdm.py (cf. STATIC_FEATURES étendu).
Usage : python scripts/bake_terrain_wetness.py [--force]
"""
from __future__ import annotations
import argparse
import heapq
import math
import os
from pathlib import Path

import numpy as np

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("VSI_CACHE", "TRUE")
os.environ.setdefault("GDAL_HTTP_TIMEOUT", "30")

import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_origin
from rasterio.crs import CRS

GRID_W, GRID_H, RES = 1601, 1051, 0.01
GRID_LEFT, GRID_TOP = -5.505, 51.505
BBOX = (-5.5, 10.5, 41.0, 51.5)       # lon_min, lon_max, lat_min, lat_max
CACHE = Path("data/cache")
_DEG_M = 111320.0
COP = ("/vsicurl/https://copernicus-dem-90m.s3.amazonaws.com/"
       "Copernicus_DSM_COG_30_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM/"
       "Copernicus_DSM_COG_30_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM.tif")
STREAM_MIN_KM2 = 25.0                  # aire drainée mini pour qu'une maille soit « cours d'eau »


def build_dem() -> np.ndarray:
    """MNT 1 km (moyenne des pixels 90 m Copernicus) aligné sur la grille Sporia."""
    dst_tr = from_origin(GRID_LEFT, GRID_TOP, RES, RES)
    dem = np.full((GRID_H, GRID_W), np.nan, np.float32)
    lon_min, lon_max, lat_min, lat_max = BBOX
    tiles = [(la, lo)
             for la in range(int(math.floor(lat_min)), int(math.ceil(lat_max)))
             for lo in range(int(math.floor(lon_min)), int(math.ceil(lon_max)))]
    n_ok = 0
    for la, lo in tiles:
        ns, ew = ("N" if la >= 0 else "S"), ("E" if lo >= 0 else "W")
        url = COP.format(ns=ns, ew=ew, lat=abs(la), lon=abs(lo))
        try:
            with rasterio.open(url) as src:
                tmp = np.full((GRID_H, GRID_W), np.nan, np.float32)
                reproject(source=rasterio.band(src, 1), destination=tmp,
                          dst_transform=dst_tr, dst_crs=CRS.from_epsg(4326),
                          src_nodata=src.nodata, dst_nodata=np.nan,
                          resampling=Resampling.average)
        except Exception:
            continue                    # tuile océan / absente
        m = np.isfinite(tmp)
        dem[m] = tmp[m]
        n_ok += 1
        print(f"  tuile {ns}{abs(la):02d} {ew}{abs(lo):03d} OK ({n_ok})", flush=True)
    print(f"MNT 1 km : {n_ok} tuiles, {100*np.isfinite(dem).mean():.0f} % couvert.")
    return dem


# Voisinage D8 : (dr, dc) et distance (m) calculée par ligne (lat).
_D8 = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]


def _cell_metrics():
    """Largeurs de maille (m) par ligne : nord-sud constant, est-ouest ∝ cos(lat)."""
    lats = (GRID_TOP - RES / 2) - np.arange(GRID_H) * RES
    dy = RES * _DEG_M
    dx = RES * _DEG_M * np.cos(np.radians(lats))
    return dx.astype(np.float64), float(dy)


def fill_depressions(dem, nodata_mask):
    """Priority-flood : remonte chaque cuvette au niveau de son exutoire (eau qui
    s'écoule jusqu'au bord). Renvoie un MNT sans dépression fermée."""
    H, W = dem.shape
    filled = np.full((H, W), np.inf, np.float64)
    visited = np.zeros((H, W), bool)
    heap = []
    # Amorçage = exutoires : toute maille VALIDE au bord de grille OU adjacente à du
    # nodata (océan/hors-couverture). La France ne touche pas les bords de grille, donc
    # seeder uniquement les bords laisserait le tas vide → on seede la frontière de la
    # zone valide. (vectorisé : dilatation du masque nodata.)
    from scipy.ndimage import binary_dilation
    edge = np.zeros((H, W), bool)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    adj_nodata = binary_dilation(nodata_mask, iterations=1) & ~nodata_mask
    seed = (~nodata_mask) & (adj_nodata | edge)
    for r, c in zip(*np.where(seed)):
        heapq.heappush(heap, (float(dem[r, c]), int(r), int(c))); visited[r, c] = True
    while heap:
        z, r, c = heapq.heappop(heap)
        filled[r, c] = z
        for dr, dc in _D8:
            nr, nc = r + dr, c + dc
            if 0 <= nr < H and 0 <= nc < W and not visited[nr, nc] and not nodata_mask[nr, nc]:
                visited[nr, nc] = True
                heapq.heappush(heap, (max(dem[nr, nc], z), nr, nc))
    filled[~np.isfinite(filled)] = np.nan
    return filled.astype(np.float32)


def flow_accum(filled, dx, dy):
    """Directions D8 (plus forte pente) + accumulation d'AIRE (m²) par ordre d'altitude
    décroissante. Renvoie (aire_drainée m², pente tangente)."""
    H, W = filled.shape
    valid = np.isfinite(filled)
    cell_area = (dx * dy)[:, None] * np.ones((1, W))     # m² par maille (par ligne)
    # direction de plus forte pente vers un voisin plus bas
    rec_r = np.full((H, W), -1, np.int32)
    rec_c = np.full((H, W), -1, np.int32)
    slope_t = np.zeros((H, W), np.float64)
    z = filled
    for r in range(H):
        for c in range(W):
            if not valid[r, c]:
                continue
            best, br, bc = 0.0, -1, -1
            for dr, dc in _D8:
                nr, nc = r + dr, c + dc
                if 0 <= nr < H and 0 <= nc < W and valid[nr, nc]:
                    dz = z[r, c] - z[nr, nc]
                    if dz > 0:
                        dist = dy if dc == 0 else (dx[r] if dr == 0 else math.hypot(dx[r], dy))
                        s = dz / dist
                        if s > best:
                            best, br, bc = s, nr, nc
            rec_r[r, c], rec_c[r, c], slope_t[r, c] = br, bc, best
    # accumulation : chaque maille pousse son aire (+ amont) vers son récepteur
    acc = cell_area.copy()
    order = np.argsort(np.where(valid, z, -np.inf), axis=None)[::-1]   # alt décroissante
    for idx in order:
        r, c = divmod(int(idx), W)
        if not valid[r, c]:
            continue
        br, bc = rec_r[r, c], rec_c[r, c]
        if br >= 0:
            acc[br, bc] += acc[r, c]
    return acc, slope_t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    out = {n: CACHE / f"{n}.npy" for n in ("twi", "tpi", "dist_water", "slope_dem")}
    if not a.force and all(p.exists() for p in out.values()):
        print("Couches wetness déjà présentes (--force pour re-baker).")
        return

    print("Bake MNT fin Copernicus GLO-90 (streaming /vsicurl)…", flush=True)
    dem = build_dem()
    nod = ~np.isfinite(dem)
    dx, dy = _cell_metrics()

    print("Remplissage des cuvettes (priority-flood)…", flush=True)
    filled = fill_depressions(np.where(nod, 1e6, dem).astype(np.float32), nod)

    print("Accumulation de flux D8…", flush=True)
    acc, slope_t = flow_accum(filled, dx, dy)

    # TWI = ln( (aire/largeur) / tan(pente) ), pente plancher pour éviter /0
    width = ((dx[:, None] + dy) / 2.0)
    sca = acc / width                                   # aire drainée spécifique (m)
    tanb = np.maximum(slope_t, 0.001)
    twi = np.log(np.maximum(sca, 1.0) / tanb).astype(np.float32)
    twi[nod] = np.nan

    # Pente (%) issue du MNT fin
    slope_pct = (slope_t * 100.0).astype(np.float32)
    slope_pct[nod] = np.nan

    # TPI : altitude − moyenne locale (fenêtre ~5 km = 5 mailles)
    from scipy.ndimage import uniform_filter
    zf = np.where(nod, np.nan, dem).astype(np.float32)
    filled_for_mean = np.where(nod, 0.0, dem)
    cnt = uniform_filter((~nod).astype(np.float32), size=5, mode="nearest")
    loc = uniform_filter(filled_for_mean, size=5, mode="nearest")
    local_mean = np.where(cnt > 0, loc / np.maximum(cnt, 1e-6), np.nan)
    tpi = (zf - local_mean).astype(np.float32)
    tpi[nod] = np.nan

    # Réseau de drainage → distance (km). Aire mini STREAM_MIN_KM2.
    from scipy.ndimage import distance_transform_edt
    stream = np.isfinite(acc) & (acc >= STREAM_MIN_KM2 * 1e6)
    if stream.any():
        # distance en mailles puis × taille de maille moyenne (≈1 km)
        dist_cells = distance_transform_edt(~stream)
        km_per_cell = float(np.nanmean((dx + dy) / 2.0)) / 1000.0
        dist_water = (dist_cells * km_per_cell).astype(np.float32)
    else:
        dist_water = np.full((GRID_H, GRID_W), np.nan, np.float32)
    dist_water[nod] = np.nan

    np.save(out["twi"], twi)
    np.save(out["tpi"], tpi)
    np.save(out["dist_water"], dist_water)
    np.save(out["slope_dem"], slope_pct)
    print(f"\nTWI        moyenne {np.nanmean(twi):.2f}  (min {np.nanmin(twi):.1f} / max {np.nanmax(twi):.1f})")
    print(f"TPI        moyenne {np.nanmean(tpi):.2f} m")
    print(f"dist_water moyenne {np.nanmean(dist_water):.1f} km  ({100*stream.mean():.1f} % mailles cours d'eau)")
    print(f"slope_dem  moyenne {np.nanmean(slope_pct):.1f} %")
    print("\nFait. Ajoute twi/tpi/dist_water aux STATIC_FEATURES de train_sdm.py.")


if __name__ == "__main__":
    main()
