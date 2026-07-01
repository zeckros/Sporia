"""Central configuration: paths resolved from the repo root (not the CWD) + web settings."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # read .env if present (dev); prod uses real env vars


class Settings:
    base_dir: Path = Path(__file__).resolve().parents[2]

    @property
    def data_dir(self) -> Path:
        return self.base_dir / "data"

    @property
    def output_tiff_dir(self) -> Path:
        return self.base_dir / "output" / "tiff"

    @property
    def web_dir(self) -> Path:
        return self.base_dir / "web"

    @property
    def overlay_dir(self) -> Path:
        return self.web_dir / "overlays"

    @property
    def data_cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def prod(self) -> bool:
        return os.environ.get("PROD") == "1"

    @property
    def session_secret(self) -> str | None:
        return os.environ.get("SESSION_SECRET")


settings = Settings()
