"""sporia.config resolves paths from the repo root, independent of the working dir."""

from __future__ import annotations

from sporia.config import settings


def test_base_dir_is_repo_root():
    assert (settings.base_dir / "pyproject.toml").is_file()


def test_paths_derive_from_base_dir():
    assert settings.data_dir == settings.base_dir / "data"
    assert settings.output_tiff_dir == settings.base_dir / "output" / "tiff"
    assert settings.overlay_dir == settings.web_dir / "overlays"


def test_prod_is_bool():
    assert isinstance(settings.prod, bool)
