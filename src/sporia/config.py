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


def resolve_session_secret(prod: bool) -> str:
    """Secret de signature de session. Fort (>=32 car., pas « change ») depuis
    SESSION_SECRET → renvoyé tel quel. En PROD sans secret fort → RuntimeError
    (refus de démarrer). En DEV → clé éphémère (sessions non persistantes)."""
    secret = os.environ.get("SESSION_SECRET") or ""
    if len(secret) >= 32 and "change" not in secret.lower():
        return secret
    if prod:
        raise RuntimeError(
            "SESSION_SECRET manquant ou faible en PROD : définissez une clé forte "
            "(>=32 caractères) dans l'environnement. Refus de démarrer."
        )
    import secrets as _secrets

    print("[WARN] SESSION_SECRET absent/faible — clé de session éphémère (DEV uniquement).")
    return _secrets.token_urlsafe(48)
