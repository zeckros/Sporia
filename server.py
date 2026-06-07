#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Serveur FastAPI de ChampiMap (frontend Tailwind/Leaflet sur-mesure).

- Sert le frontend statique (web/) et les overlays PNG (web/overlays/).
- Auth par comptes (config.yaml, bcrypt) + session cookie signée (SessionMiddleware).
- API JSON qui réutilise champi_core (rasters, overlays, communes, favorabilité, point).

Lancement (dev)  :  python -m uvicorn server:app --host 0.0.0.0 --port 8000
Lancement (prod) :  PROD=1 uvicorn server:app --host 127.0.0.1 --port 8000   (derrière nginx/TLS)
"""
from __future__ import annotations
import os
import re
from pathlib import Path

import bcrypt
import yaml
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel

import champi_core as core
import user_prefs
import user_spots
import access_requests

# Métadonnées (nom FR, couleur) par latin, pour habiller les listes d'espèces.
_SPECIES_META = {m["latin"]: m for m in core.MUSHROOMS}


def _catalog() -> list[dict]:
    """Catalogue exposé à l'UI (sélection « Mes champignons ») : uniquement les
    espèces réellement modélisées/servies (cf. core.fruiting_models). On n'affiche
    jamais une espèce dont aucun modèle n'est servi — p.ex. la morille, non
    modélisable. Ordre conservé = celui (saisonnier) de core.MUSHROOMS."""
    served = set(core.fruiting_models())
    return [{"latin": m["latin"], "nom": m["nom"], "color": m["color"]}
            for m in core.MUSHROOMS if m["latin"] in served]


def _valid_latins() -> set[str]:
    """Latins acceptés en entrée (préférences, filtres CSV) = espèces servies."""
    return set(core.fruiting_models())

CONFIG_PATH = Path("config.yaml")
WEB_DIR = Path("web")
OVERLAY_DIR = WEB_DIR / "overlays"

# PROD=1 active les protections de production (cookie HTTPS-only, /docs masqué).
PROD = os.environ.get("PROD") == "1"


def _load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


_cfg = _load_config()
# Secret de signature de session : variable d'env prioritaire, sinon clé de config.yaml.
_SESSION_SECRET = os.environ.get("SESSION_SECRET") or _cfg.get("cookie", {}).get("key", "")
if not _SESSION_SECRET or "change" in _SESSION_SECRET.lower() or len(_SESSION_SECRET) < 32:
    # Clé absente/faible : on génère une clé éphémère (les sessions ne survivront pas à un
    # redémarrage). En prod, DÉFINIR SESSION_SECRET ou une cookie.key forte (>=32 octets).
    import secrets as _secrets
    _SESSION_SECRET = _secrets.token_urlsafe(48)
    print("[WARN] cookie.key faible/absente — secret de session éphémère généré. "
          "Définissez SESSION_SECRET (env) ou une cookie.key forte dans config.yaml pour la prod.")

app = FastAPI(title="Sporia",
              docs_url=None if PROD else "/docs",
              redoc_url=None if PROD else "/redoc",
              openapi_url=None if PROD else "/openapi.json")
app.add_middleware(
    SessionMiddleware,
    secret_key=_SESSION_SECRET,
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=PROD,           # cookie envoyé uniquement en HTTPS en prod
)


# Content-Security-Policy : autorise uniquement les CDN réellement utilisés par
# l'UI (Tailwind, Leaflet/unpkg, Google Fonts) + les tuiles carto/IGN en image.
# 'unsafe-inline' est nécessaire (config Tailwind + styles inline dans index.html) ;
# les données utilisateur rendues en HTML sont par ailleurs échappées (escapeHtml).
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://unpkg.com https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https:; "          # overlays (self) + tuiles CARTO/IGN (https)
    "connect-src 'self'; "
    "frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Content-Security-Policy", _CSP)
    return resp


# ===== Validation des entrées (anti path-traversal sur les noms de fichiers rasters) =====
_DATE_RE = re.compile(r"^\d{8}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_date(d: str) -> str:
    if not _DATE_RE.match(d or ""):
        raise HTTPException(status_code=400, detail="Paramètre 'date' invalide (attendu AAAAMMJJ).")
    return d


def _valid_dates(s: str) -> list[str]:
    ds = [d for d in (s or "").split(",") if d]
    if not ds or not all(_DATE_RE.match(d) for d in ds):
        raise HTTPException(status_code=400, detail="Paramètre 'dates' invalide (liste AAAAMMJJ).")
    return ds


def _valid_var(v: str) -> str:
    v = (v or "").upper()
    if v not in ("RR", "T"):
        raise HTTPException(status_code=400, detail="Paramètre 'var' invalide (RR ou T).")
    return v


# ===== Auth =====
# Hash bcrypt « leurre » : vérifié quand l'identifiant n'existe pas, pour que le
# temps de réponse soit constant (anti-énumération d'identifiants par chronométrage).
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt())


def _verify(username: str, password: str):
    users = _cfg.get("credentials", {}).get("usernames", {})
    u = users.get(username)
    try:
        if u is None:
            bcrypt.checkpw(password.encode("utf-8"), _DUMMY_HASH)   # temps constant
            return None
        if bcrypt.checkpw(password.encode("utf-8"), u["password"].encode("utf-8")):
            return {"username": username, "name": u.get("name", username)}
    except Exception:
        return None
    return None


def require_user(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    return user


class Credentials(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(body: Credentials, request: Request):
    user = _verify(body.username, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Identifiant ou mot de passe incorrect.")
    request.session["user"] = user
    return {"ok": True, "name": user["name"]}


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    user = request.session.get("user")
    return {"authenticated": bool(user), "name": user["name"] if user else None}


# ===== API données (protégées) =====
@app.get("/api/dates")
def api_dates(user=Depends(require_user)):
    return {"dates": [d.strftime("%Y%m%d") for d in core.available_dates()]}


@app.get("/api/cities")
def api_cities(q: str = "", user=Depends(require_user)):
    return {"results": core.search_cities(q)}


@app.get("/api/outline")
def api_outline(user=Depends(require_user)):
    return core.france_outline_geojson() or {}


@app.get("/api/overlay")
def api_overlay(var: str, dates: str, user=Depends(require_user)):
    var = _valid_var(var)
    ds = _valid_dates(dates)
    res = core.render_weather_overlay(var, ds)
    if res is None:
        raise HTTPException(status_code=404, detail="Aucune donnée pour cette période.")
    return res


def _parse_species(s: str) -> list[str]:
    """CSV de noms latins → liste validée (sous-ensemble du catalogue servi)."""
    valid = _valid_latins()
    return [x.strip() for x in (s or "").split(",") if x.strip() in valid]


class SpeciesPrefs(BaseModel):
    species: list[str]


@app.get("/api/preferences")
def api_get_preferences(user=Depends(require_user)):
    catalog = _catalog()
    latins = {s["latin"] for s in catalog}
    sel = user_prefs.get_species(user["username"])
    # On restreint la sélection enregistrée au catalogue servi : une espèce retirée
    # du modèle (p.ex. morille déjà enregistrée par un compte) ne réapparaît pas.
    # Si rien de servi ne subsiste, on retombe sur « toutes les espèces servies ».
    kept = [s for s in sel if s in latins] if sel is not None else None
    return {"species": kept or [s["latin"] for s in catalog],
            "all": catalog, "saved": bool(kept)}


@app.post("/api/preferences")
def api_set_preferences(body: SpeciesPrefs, user=Depends(require_user)):
    valid_set = _valid_latins()
    valid = [s for s in body.species if s in valid_set]
    if not valid:
        raise HTTPException(status_code=400, detail="Sélection vide ou invalide.")
    user_prefs.set_species(user["username"], valid)
    return {"ok": True, "species": valid}


@app.get("/api/favorability")
def api_favorability(date: str, species: str | None = None, user=Depends(require_user)):
    # `species` explicite (CSV) sinon préférences enregistrées du compte (sinon toutes).
    sp = _parse_species(species) if species is not None else user_prefs.get_species(user["username"])
    res = core.render_favorability_overlay(_valid_date(date), species=sp)
    if res is None:
        raise HTTPException(status_code=404, detail="Favorabilité indisponible.")
    return res


@app.get("/api/soil")
def api_soil(user=Depends(require_user)):
    res = core.render_soil_overlay()
    if res is None:
        raise HTTPException(status_code=404, detail="Couche type de sol indisponible.")
    return res


@app.get("/api/soil-moisture")
def api_soil_moisture(date: str | None = None, user=Depends(require_user)):
    res = core.render_soil_moisture_overlay(_valid_date(date) if date else None)
    if res is None:
        raise HTTPException(status_code=404, detail="Couche humidité du sol indisponible.")
    return res


@app.get("/api/altitude")
def api_altitude(user=Depends(require_user)):
    res = core.render_altitude_overlay()
    if res is None:
        raise HTTPException(status_code=404, detail="Couche altitude indisponible.")
    return res


@app.get("/api/aspect")
def api_aspect(user=Depends(require_user)):
    res = core.render_aspect_overlay()
    if res is None:
        raise HTTPException(status_code=404, detail="Couche exposition indisponible.")
    return res


@app.get("/api/radar")
def api_radar(date: str | None = None, species: str | None = None, user=Depends(require_user)):
    """« Radar à champignons » : carte habitat×moment agrégée sur la sélection du compte
    (ou `species` CSV), restreinte aux espèces ayant un modèle servi."""
    sel = _parse_species(species) if species is not None else user_prefs.get_species(user["username"])
    served = set(core.fruiting_models())
    sel = [s for s in (sel or [m["latin"] for m in core.MUSHROOMS]) if s in served]
    res = core.render_radar_overlay(sel, _valid_date(date) if date else None)
    if res is None:
        raise HTTPException(status_code=404, detail="Radar indisponible (aucune espèce modélisée sélectionnée).")
    return res


@app.get("/api/fruiting-models")
def api_fruiting_models(user=Depends(require_user)):
    """Espèces disposant d'un modèle « pousse en ce moment » (point #4)."""
    latins = core.fruiting_models()
    by_latin = {m["latin"]: m for m in core.MUSHROOMS}
    return {"species": [{"latin": l, "nom": by_latin.get(l, {}).get("nom", l)} for l in latins]}


@app.get("/api/fruiting")
def api_fruiting(species: str, date: str | None = None, user=Depends(require_user)):
    """Carte de probabilité de fructification du jour pour une espèce (modèle
    météo-dépendant appliqué aux ~21 derniers jours via Open-Meteo)."""
    if species not in core.fruiting_models():
        raise HTTPException(status_code=404, detail="Aucun modèle de pousse pour cette espèce.")
    res = core.render_fruiting_overlay(species, _valid_date(date) if date else None)
    if res is None:
        raise HTTPException(status_code=503, detail="Indice de pousse indisponible (météo récente).")
    return res


@app.get("/api/point")
def api_point(lat: float, lon: float, date: str, user=Depends(require_user)):
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="Coordonnées invalides.")
    sel = user_prefs.get_species(user["username"])
    return core.point_report(lat, lon, _valid_date(date), selected=sel)


@app.get("/api/forest")
def api_forest(lat: float, lon: float, user=Depends(require_user)):
    """Essence précise au point (BD Forêt WMS) — appelée en différé par l'UI, hors
    du chemin critique du clic (qui n'utilise que la famille bakée). Best-effort."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="Coordonnées invalides.")
    import mushroom_map as mmap
    return mmap.forest_at_point(round(lat, 4), round(lon, 4)) or {}


# ===== Spots enregistrés (« mes coins ») + alerte « propice » =====
class SpotIn(BaseModel):
    lat: float
    lon: float
    name: str | None = None


class SpotPatch(BaseModel):
    name: str


@app.get("/api/spots")
def api_list_spots(user=Depends(require_user)):
    """Spots du compte enrichis du statut « propice » courant (échantillonné sur
    le radar habitat × pousse du jour, selon la sélection d'espèces du compte)."""
    spots = user_spots.list_spots(user["username"])
    sel = user_prefs.get_species(user["username"])
    return {"spots": core.spots_status(spots, selected=sel)}


@app.post("/api/spots")
def api_add_spot(body: SpotIn, user=Depends(require_user)):
    if not (-90 <= body.lat <= 90 and -180 <= body.lon <= 180):
        raise HTTPException(status_code=400, detail="Coordonnées invalides.")
    spot = user_spots.add_spot(user["username"], body.lat, body.lon, body.name or "")
    return {"ok": True, "spot": spot}


@app.patch("/api/spots/{spot_id}")
def api_rename_spot(spot_id: str, body: SpotPatch, user=Depends(require_user)):
    if not (body.name or "").strip():
        raise HTTPException(status_code=400, detail="Nom vide.")
    if not user_spots.rename_spot(user["username"], spot_id, body.name):
        raise HTTPException(status_code=404, detail="Spot introuvable.")
    return {"ok": True}


@app.delete("/api/spots/{spot_id}")
def api_delete_spot(spot_id: str, user=Depends(require_user)):
    if not user_spots.delete_spot(user["username"], spot_id):
        raise HTTPException(status_code=404, detail="Spot introuvable.")
    return {"ok": True}


# ===== Demande d'accès / contact (site sur invitation) =====
class AccessRequestIn(BaseModel):
    name: str
    email: str
    message: str
    hp: str | None = None          # honeypot anti-bot (doit rester vide)


@app.post("/api/access-request")
def api_access_request(body: AccessRequestIn):
    """Demande d'accès publique (non authentifiée). Honeypot + validation + cap.
    Rate-limitée par nginx (zone /api/)."""
    if (body.hp or "").strip():                    # bot : on fait comme si OK, sans rien stocker
        return {"ok": True}
    name = (body.name or "").strip()
    email = (body.email or "").strip()
    message = (body.message or "").strip()
    if not name or len(name) > 80:
        raise HTTPException(status_code=400, detail="Nom invalide.")
    if not _EMAIL_RE.match(email) or len(email) > 120:
        raise HTTPException(status_code=400, detail="Email invalide.")
    if not message or len(message) > 2000:
        raise HTTPException(status_code=400, detail="Message invalide (1–2000 caractères).")
    access_requests.add_request(name, email, message)
    return {"ok": True}


@app.get("/api/access-requests")
def api_list_access_requests(user=Depends(require_user)):
    """Liste des demandes d'accès (réservé aux comptes connectés / admin)."""
    return {"requests": access_requests.list_requests()}


# ===== Statique =====
OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/overlays", StaticFiles(directory=str(OVERLAY_DIR)), name="overlays")
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
def index():
    # no-cache sur le document HTML → la référence versionnée de app.js est toujours fraîche
    return FileResponse(str(WEB_DIR / "index.html"),
                        headers={"Cache-Control": "no-cache, must-revalidate"})
