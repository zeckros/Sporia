"""species.yaml loads into the exact legacy shape (months: set; pairs: tuple)."""

from __future__ import annotations

from sporia.domain.species import MUSHROOMS, guild_of


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
