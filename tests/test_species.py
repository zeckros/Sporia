"""species.yaml loads into the exact legacy shape (months: set; pairs: tuple)."""

from __future__ import annotations

from sporia.domain.species import MUSHROOMS, guild_of, habitat_feature_subset


def test_species_count():
    assert len(MUSHROOMS) == 14


def test_types_match_legacy_shape():
    cepe = next(m for m in MUSHROOMS if m["latin"] == "Boletus edulis")
    assert cepe["months"] == {8, 9, 10, 11}  # set
    assert cepe["rain_lag"] == (7, 16)  # tuple
    assert cepe["ph_opt"] == (4.5, 6.5)  # tuple
    assert isinstance(cepe["months"], set)


def test_optional_alt_opt():
    aereus = next(m for m in MUSHROOMS if m["latin"] == "Boletus aereus")
    assert aereus["alt_opt"] == (0, 900)
    assert "alt_opt" not in next(m for m in MUSHROOMS if m["latin"] == "Boletus edulis")


_OPEN = ["Calocybe gambosa", "Agaricus campestris", "Macrolepiota procera"]


def test_guild_assignments():
    assert guild_of("Boletus edulis") == "ecto"
    for sp in _OPEN:
        assert guild_of(sp) == "open"
    assert guild_of("Pleurotus ostreatus") == "sapro"


def test_guild_default_unknown():
    assert guild_of("Inconnu inconnu") == "ecto"


def test_every_species_has_guild():
    for m in MUSHROOMS:
        assert m.get("guild") in {"ecto", "open", "sapro"}, m["latin"]


_FEATS = [
    "forest_density",
    "ph",
    "clay",
    "sand",
    "silt",
    "altitude",
    "slope",
    "northness",
    "twi",
    "tpi",
    "dist_water",
    "slope_dem",
    "soc",
    "cec",
    "edge_density",
    "clim_bio1",
    "lc_grass",
    "lc_tree",
    "host_chene",
    "host_hetre",
]


def test_ecto_keeps_everything():
    assert habitat_feature_subset(_FEATS, "Boletus edulis") == _FEATS


def test_sapro_drops_host_only():
    out = habitat_feature_subset(_FEATS, "Pleurotus ostreatus")
    assert "forest_density" in out  # structure forestière conservée
    assert not any(f.startswith("host_") for f in out)  # host_* retiré


def test_open_lean_set():
    out = habitat_feature_subset(_FEATS, "Calocybe gambosa")
    for f in [
        "forest_density",
        "twi",
        "tpi",
        "slope_dem",
        "edge_density",
        "host_chene",
        "host_hetre",
    ]:
        assert f not in out, f
    for f in [
        "ph",
        "clay",
        "sand",
        "silt",
        "soc",
        "cec",
        "dist_water",
        "altitude",
        "slope",
        "northness",
        "clim_bio1",
        "lc_grass",
        "lc_tree",
    ]:
        assert f in out, f


def test_open_preserves_order():
    out = habitat_feature_subset(_FEATS, "Agaricus campestris")
    assert out == [f for f in _FEATS if f in out]


_FEATS_FTEU = [
    "forest_density",
    "ph",
    "clim_bio1",
    "lc_grass",
    "host_chene",
    "host_hetre",
    "fteu_broadleaf",
    "fteu_needleleaf",
    "fteu_mixed",
]


def test_ecto_cross_border_swaps_host_for_fteu():
    out = habitat_feature_subset(_FEATS_FTEU, "Boletus edulis", cross_border=True)
    assert not any(f.startswith("host_") for f in out)  # host fin retiré
    for f in ["fteu_broadleaf", "fteu_needleleaf", "fteu_mixed"]:
        assert f in out  # forêt-EU ajoutée
    assert "forest_density" in out and "clim_bio1" in out  # reste inchangé


def test_ecto_fr_only_keeps_host_drops_fteu():
    out = habitat_feature_subset(_FEATS_FTEU, "Boletus edulis", cross_border=False)
    assert "host_chene" in out  # host fin gardé
    assert not any(f.startswith("fteu_") for f in out)  # fteu_* exclu


def test_open_ignores_fteu_and_cross_border():
    a = habitat_feature_subset(_FEATS_FTEU, "Calocybe gambosa", cross_border=False)
    b = habitat_feature_subset(_FEATS_FTEU, "Calocybe gambosa", cross_border=True)
    assert a == b  # open : cross_border sans effet
    assert not any(f.startswith(("host_", "fteu_")) for f in a)
