"""Characterization of the rule-based suitability model (champi_core).

These assert exact current outputs so extraction to domain/suitability.py cannot drift."""

from __future__ import annotations

import pytest

import champi_core as core

CEPE = next(m for m in core.MUSHROOMS if m["latin"] == "Boletus edulis")  # months {8,9,10,11}


def test_ph_match_bands():
    assert core._ph_match(None, (4.5, 6.5)) == "unknown"
    assert core._ph_match(5.5, (4.5, 6.5)) == "ok"
    assert core._ph_match(6.7, (4.5, 6.5)) == "ok"  # within +0.3
    assert core._ph_match(7.3, (4.5, 6.5)) == "mid"  # within +1.0
    assert core._ph_match(8.0, (4.5, 6.5)) == "no"


def test_altitude_fit_bounds():
    assert core._altitude_fit_point(None, (0, 900)) == 1.0
    assert 0.3 <= core._altitude_fit_point(3000, (0, 900)) <= 1.0
    assert core._altitude_fit_point(500, (0, 900)) == pytest.approx(1.0)


def test_suitability_out_of_season():
    w = {
        "month": 3,
        "temp_mean": 15,
        "soil_temp": 14,
        "days_since_rain": 8,
        "rain14": 40,
        "soil_moisture": 0.3,
    }
    assert core.mushroom_suitability(CEPE, w) == ("Hors saison", "off", 3, "unknown")


def test_suitability_favorable():
    w = {
        "month": 9,
        "temp_mean": 16,
        "soil_temp": 16,
        "days_since_rain": 10,
        "rain14": 40,
        "soil_moisture": 0.3,
    }
    label, level, prio, phm = core.mushroom_suitability(
        CEPE, w, soil={"ph": 5.5}, terrain={"altitude": 400, "northness": 0.0}
    )
    assert (label, level) == ("Favorable", "good")
    assert phm == "ok"


def test_suitability_partial_when_dry_and_no_recent_rain():
    w = {
        "month": 9,
        "temp_mean": 16,
        "soil_temp": 16,
        "days_since_rain": 30,
        "rain14": 0,
        "soil_moisture": 0.05,
    }
    label, level, prio, phm = core.mushroom_suitability(CEPE, w, soil={"ph": 5.5})
    assert level in {"mid", "bad"}
