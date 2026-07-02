"""Lieux & dates — recherche de communes/villes, contour France, dates de rasters
disponibles. Extrait de champi_core (iso-comportement)."""

from __future__ import annotations

import datetime
from functools import lru_cache

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, mapping

from sporia.config import settings

VILLES_CSV = str(settings.data_dir / "villes_france.csv")
COMMUNES_GPKG = str(settings.data_dir / "communes.gpkg")
DATA_DIR = settings.output_tiff_dir


@lru_cache(maxsize=1)
def _static():
    villes = pd.read_csv(VILLES_CSV, sep=";")
    for c in ["nom1", "nom2", "nom3", "nom4", "code_postal"]:
        if c not in villes.columns:
            villes[c] = ""
    villes["all_names"] = (
        villes[["nom1", "nom2", "nom3", "nom4", "code_postal"]]
        .astype(str)
        .agg(" ".join, axis=1)
        .str.lower()
    )
    comm = gpd.read_file(COMMUNES_GPKG)
    if comm.crs and comm.crs.to_epsg() != 4326:
        comm = comm.to_crs("EPSG:4326")
    comm = comm.dropna(subset=["geometry"])
    france_boundary = comm.geometry.union_all()

    outline_gdf = None
    try:
        comm_proj = comm.to_crs("EPSG:2154")
        centroids = gpd.GeoSeries(comm_proj.geometry.centroid, crs="EPSG:2154").to_crs("EPSG:4326")
        mask_c = centroids.x.between(-10.0, 12.0) & centroids.y.between(41.0, 52.0)
        mainland = comm[mask_c].copy()
        rep = mainland.geometry.representative_point()
        mainland["sample_lon"] = rep.x
        mainland["sample_lat"] = rep.y
        name_col = next(
            (
                c
                for c in ["DCOE_L_LIB", "nom", "name", "NOM_COM", "NOM_COMM", "NOM", "libelle"]
                if c in mainland.columns
            ),
            None,
        )
        if name_col:
            mainland = mainland.rename(columns={name_col: "nom_com"})
        cols = ["geometry", "sample_lon", "sample_lat"] + (
            ["nom_com"] if "nom_com" in mainland.columns else []
        )
        outline_gdf = mainland[cols].copy()
        outline_gdf.geometry = outline_gdf.geometry.simplify(0.01, preserve_topology=False)
        outline_gdf = outline_gdf.rename(columns={"sample_lon": "lon", "sample_lat": "lat"})
    except Exception:
        outline_gdf = None
    return villes, comm, france_boundary, outline_gdf


def search_cities(query: str, limit: int = 12):
    villes, *_ = _static()
    q = (query or "").strip().lower()
    if not q:
        return []
    m = villes[villes["all_names"].str.contains(q, na=False)].head(limit)
    out = []
    for _, r in m.iterrows():
        out.append(
            {
                "label": f"{r['nom1']} ({r['code_postal']})",
                "name": str(r["nom1"]),
                "lat": float(r["latitude"]),
                "lon": float(r["longitude"]),
            }
        )
    return out


def find_commune_at(lat: float, lon: float):
    _, _, _, outline_gdf = _static()
    if outline_gdf is None or outline_gdf.empty:
        return None
    try:
        pt = Point(lon, lat)
        idx = list(outline_gdf.sindex.query(pt, predicate="intersects"))
        if idx:
            return outline_gdf.iloc[idx[0]]
        dists = outline_gdf.geometry.distance(pt)
        nearest = dists.idxmin()
        if dists[nearest] < 0.05:
            return outline_gdf.loc[nearest]
    except Exception:
        pass
    return None


@lru_cache(maxsize=1)
def france_outline_geojson():
    _, _, france_boundary, _ = _static()
    if france_boundary is None:
        return None
    try:
        return mapping(france_boundary.simplify(0.01, preserve_topology=True))
    except Exception:
        return None


def available_dates():
    out = []
    for f in DATA_DIR.glob("RR_*.tif"):
        try:
            out.append(
                datetime.datetime.strptime(f.stem.replace("RR_", "").split("_")[0], "%Y%m%d").date()
            )
        except Exception:
            pass
    return sorted(set(out))
