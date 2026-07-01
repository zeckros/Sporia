"""species.yaml loads into the exact legacy shape (months: set; pairs: tuple)."""

from __future__ import annotations

from sporia.domain.species import MUSHROOMS


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
