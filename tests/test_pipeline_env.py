"""Régressions du refactor 2026-07-02 (`c1656dc24`, pipeline déplacé dans src/sporia/).

Ce déplacement a laissé deux chemins résolus par rapport au *fichier* et non à la
racine du dépôt : le `.env` des clés Météo-France et l'import de `interpret_day`.
Conséquence en production : la collecte a tourné deux mois en renvoyant le code 0
sans jamais rien télécharger. Ces tests verrouillent les deux points.
"""

from __future__ import annotations

import importlib

import pytest

from sporia.config import settings

KEY_NAMES = ("API_KEY_AROME", "API_KEY_STATIONS", "API_KEY_RADAR")


@pytest.fixture(scope="module")
def collect_day():
    return importlib.import_module("sporia.pipeline.collect_day")


def test_env_path_points_to_repo_root(collect_day):
    """Le .env lu doit être celui de la racine, quel que soit l'emplacement du module."""
    assert collect_day.ENV_PATH == settings.base_dir / ".env"


def test_missing_api_keys_lists_absent_names(collect_day, monkeypatch):
    for name in KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    assert collect_day.missing_api_keys() == list(KEY_NAMES)


def test_missing_api_keys_reports_only_the_absent_one(collect_day, monkeypatch):
    monkeypatch.setenv("API_KEY_AROME", "x")
    monkeypatch.setenv("API_KEY_STATIONS", "x")
    monkeypatch.delenv("API_KEY_RADAR", raising=False)
    assert collect_day.missing_api_keys() == ["API_KEY_RADAR"]


def test_missing_api_keys_empty_when_all_set(collect_day, monkeypatch):
    for name in KEY_NAMES:
        monkeypatch.setenv(name, "x")
    assert collect_day.missing_api_keys() == []


def test_no_stale_top_level_interpret_day_import():
    """`from interpret_day import ...` ne résout plus rien depuis le déplacement :
    l'import doit être qualifié par le paquet."""
    for rel in ("src/sporia/pipeline/collect_day.py", "src/sporia/enrich/terrain.py"):
        src = (settings.base_dir / rel).read_text(encoding="utf-8")
        assert "from interpret_day import" not in src, f"{rel} : import obsolète du refactor"
