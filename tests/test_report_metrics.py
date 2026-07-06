"""Parsing du récap habitat (colonne BoyceSE) dans report_metrics."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import report_metrics as rm  # noqa: E402


def test_parse_habitat_captures_se(monkeypatch):
    log = "Boletus edulis                       1052  0.683  0.690  0.026\n"
    monkeypatch.setattr(rm, "_read", lambda p: log if "sdm" in p else "")
    hab = rm.parse_habitat()
    assert hab["Boletus edulis"] == (0.683, 0.690, 0.026)


def test_parse_habitat_nan_se_kept_as_none(monkeypatch):
    log = "Boletus edulis                       1052  0.683  0.690      nan\n"
    monkeypatch.setattr(rm, "_read", lambda p: log if "sdm" in p else "")
    hab = rm.parse_habitat()
    assert hab["Boletus edulis"] == (0.683, 0.690, None)  # ligne conservée, SE None


def test_parse_habitat_old_log_without_se(monkeypatch):
    log = "Boletus edulis                       1052  0.683  0.690\n"
    monkeypatch.setattr(rm, "_read", lambda p: log if "sdm" in p else "")
    hab = rm.parse_habitat()
    assert hab["Boletus edulis"] == (0.683, 0.690, None)
