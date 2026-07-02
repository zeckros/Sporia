"""Surface API agrégée de Sporia — ré-exporte le public (domain, geo, overlays,
places, points) consommé par la couche web et les scripts. Remplace l'ancien champi_core."""

from sporia.domain.species import MUSHROOMS  # noqa: F401
from sporia.domain.suitability import (  # noqa: F401
    PROPICE_MIN,
    PROPICE_PCT,
    RADAR_VMAX,
    _altitude_fit_point,
    _aspect_fit_point,
    _ph_match,
    _radar_label,
    mushroom_suitability,
)
from sporia.geo.rasters import (  # noqa: F401
    _aggregate,
    _forest_mask,
    _france_mask,
    _grid_ref,
    _grid_ref_geo,
    _mask_to_france,
    _reproject_to_3857,
    _reproject_to_grid,
    _tile_bbox_3857,
    sample_raster,
)
from sporia.geo.render import (  # noqa: F401
    _blank_tile,
    _bust,
    _hex_to_rgb,
    _render_grid_overlay,
    _save_png,
)
from sporia.overlays.favorability import render_favorability_overlay  # noqa: F401
from sporia.overlays.fruiting import fruiting_models, render_fruiting_overlay  # noqa: F401
from sporia.overlays.radar import (  # noqa: F401
    _forest_alpha_from_mask,
    _forest_tile_alpha,
    _radar_grid,
    _radar_species_params,
    radar_tile_png,
    radar_tile_species,
    render_radar_overlay,
)
from sporia.overlays.soil import render_soil_moisture_overlay, render_soil_overlay  # noqa: F401
from sporia.overlays.terrain import render_altitude_overlay, render_aspect_overlay  # noqa: F401
from sporia.overlays.weather import render_weather_overlay  # noqa: F401
from sporia.places import (  # noqa: F401
    _static,
    available_dates,
    find_commune_at,
    france_outline_geojson,
    search_cities,
)
from sporia.points import analyze_point_weather, point_report, spots_status  # noqa: F401
