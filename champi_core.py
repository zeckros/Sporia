#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cœur métier ChampiMap — Python pur (AUCUNE dépendance Streamlit).

Réutilisé par le serveur FastAPI (server.py). Reprend la logique de l'ancienne app
Streamlit : accès rasters météo, communes, rendu des overlays (météo + favorabilité
champignons), analyse météo d'un point et associations essence↔champignon (via
mushroom_map.py).

Sorties overlays : PNG écrits dans web/overlays/, servis en statique par FastAPI.
"""
from __future__ import annotations
import hashlib
import datetime
import math
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio import features
from rasterio.crs import CRS as RioCRS
from rasterio.warp import (reproject as rio_reproject, calculate_default_transform,
                           Resampling as RioResampling, transform_bounds as rio_transform_bounds)
import geopandas as gpd
from shapely.geometry import Point, mapping
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import mushroom_map as mmap
import soil_data
import terrain_data
import fruiting_live
from sporia.domain.species import MUSHROOMS
from sporia.domain.suitability import (  # noqa: F401  (re-export legacy facade)
    _ph_match, _altitude_fit_point, _aspect_fit_point, mushroom_suitability,
    _radar_label, RADAR_VMAX, PROPICE_MIN, PROPICE_PCT,
)

from sporia.geo.rasters import (  # noqa: F401  (re-export legacy facade)
    sample_raster, _france_mask, _aggregate, _reproject_to_3857, _reproject_to_grid,
    _forest_mask, _grid_ref, _mask_to_france, _tile_bbox_3857, _grid_ref_geo,
)
from sporia.geo.render import (  # noqa: F401
    _save_png, _bust, _render_grid_overlay, _blank_tile, _hex_to_rgb,
)

from sporia.places import (  # noqa: F401  (re-export legacy facade)
    _static, search_cities, find_commune_at, france_outline_geojson, available_dates,
)

from sporia.overlays.favorability import render_favorability_overlay  # noqa: F401
from sporia.overlays.fruiting import fruiting_models, render_fruiting_overlay  # noqa: F401
from sporia.overlays.radar import (  # noqa: F401
    _forest_alpha_from_mask, _forest_tile_alpha, _radar_grid, _radar_species_params,
    radar_tile_png, radar_tile_species, render_radar_overlay,
)
from sporia.overlays.soil import render_soil_moisture_overlay, render_soil_overlay  # noqa: F401
from sporia.overlays.terrain import render_altitude_overlay, render_aspect_overlay  # noqa: F401
from sporia.overlays.weather import render_weather_overlay  # noqa: F401

from sporia.points import analyze_point_weather, point_report, spots_status  # noqa: F401
# ===== Configuration =====
DATA_DIR = Path("output/tiff")
VILLES_CSV = "data/villes_france.csv"
COMMUNES_GPKG = "data/communes.gpkg"
OVERLAY_DIR = Path("web/overlays")
OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
MASK_CACHE = Path("data/cache")
MASK_CACHE.mkdir(parents=True, exist_ok=True)

# Affichage des « zones à champignons » calé sur la couche forêt (densité BD Forêt).
# Sous FOREST_MIN : strictement rien (pas de forêt → invisible). Entre FOREST_MIN et
# FOREST_FULL : l'opacité monte avec le couvert (bois clairsemé = léger, forêt dense
# = pleine opacité). Les champignons étant en forêt, l'overlay suit ainsi les bois.




# ===== Données statiques (chargées une fois) =====








# ===== Dates / rasters =====












# Table de couleurs YlGn pré-calculée (uint8) → colorisation des grands rendus sans
# passer par du float64 matplotlib (qui exploserait la mémoire sur une grande image).

# Masque forêt haute résolution (BD Forêt®, baké par scripts/bake_forest_mask.py).
























# Espèces exclues de la MODÉLISATION (habitat SDM + calque « pousse en ce moment »)
# car non modélisables avec nos couches. N'ayant aucun modèle servi, elles ne sont
# PAS affichées dans l'UI (ni sélection « Mes champignons » ni fiche point) ; leur
# entrée MUSHROOMS subsiste uniquement comme métadonnée (host_match, etc.).
#   • Morchella esculenta : écologie de perturbation (ripisylve/frênaies/brûlis/
#     calcaire) absente de nos prédicteurs + biais GBIF urbain ; Boyce reste ≤ 0
#     même après filtre anti-urbain et distance-eau.








# ===== « Radar à champignons » en TUILES (contours forêt exacts à tous les zooms) =====
# Une tuile = valeur (habitat×pousse) 1 km RÉÉCHANTILLONNÉE LISSE (bilinéaire) à la résolution
# du zoom, CLIPPÉE au contour forêt via la tuile BD Forêt WMTS de mêmes z/x/y (pixel-alignée
# → contours exacts, identiques au calque forêt). Rendu mis en cache disque.
# Contour forêt du radar : tuile BD Forêt WMTS pixel-exacte (bordures NETTES) à partir de
# ce zoom, masque baké 400 m en-dessous. Mis à 0 → contours nets À TOUS LES ZOOMS, servis
# depuis le cache disque pré-rempli (scripts/bake_forest_tiles.py) : zéro réseau en régime
# permanent. Le masque ne sert plus que de repli si une tuile WMTS manque encore au cache.
# (Le zoom natif du radar est plafonné côté carte → on n'a jamais besoin de z > FOREST_MAX_Z.)




















# ===== Statut « propice » des spots enregistrés =====
# L'indice du radar est calé sur une ÉCHELLE ABSOLUE (RADAR_VMAX), pas sur le P99 du
# jour : en période globalement défavorable la carte reste sombre (et non « la moins
# pire = 100 % »). Un spot est « vraiment propice » quand l'indice dépasse les deux
# seuils ci-dessous. Tous volontairement faciles à ajuster.






# ===== Overlay « type de sol » (classes texturales SoilGrids) =====
# Palette pédologique : sable=jaune → limon=olive → argile=brun-rouge.






# ===== Analyse météo d'un point + champignons =====
