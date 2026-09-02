#!/usr/bin/env python3
"""
Serveur FastAPI de ChampiMap (frontend Tailwind/Leaflet sur-mesure).

- Sert le frontend statique (web/) et les overlays PNG (web/overlays/).
- Auth par comptes (config.yaml, bcrypt) + session cookie signée (SessionMiddleware).
- API JSON qui réutilise champi_core (rasters, overlays, communes, favorabilité, point).

Lancement (dev)  :  python -m uvicorn sporia.web.app:app --host 0.0.0.0 --port 8000
Lancement (prod) :  PROD=1 uvicorn sporia.web.app:app --host 127.0.0.1 --port 8000  (nginx/TLS)
"""

from __future__ import annotations

import html
import os
import re
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from sporia import api as core
from sporia import billing
from sporia.config import resolve_session_secret, settings
from sporia.domain import metrics
from sporia.email import send_email
from sporia.enrich import forest as mmap
from sporia.users import access_requests, accounts
from sporia.users import prefs as user_prefs
from sporia.users import spots as user_spots
from sporia.web.auth import require_admin, require_subscription, require_user, verify
from sporia.web.security import security_headers

# Métadonnées (nom FR, couleur) par latin, pour habiller les listes d'espèces.
_SPECIES_META = {m["latin"]: m for m in core.MUSHROOMS}


def _catalog() -> list[dict]:
    """Catalogue exposé à l'UI (sélection « Mes champignons ») : uniquement les
    espèces réellement modélisées/servies (cf. core.fruiting_models). On n'affiche
    jamais une espèce dont aucun modèle n'est servi — p.ex. la morille, non
    modélisable. Ordre conservé = celui (saisonnier) de core.MUSHROOMS."""
    served = set(core.fruiting_models())
    return [
        {
            "latin": m["latin"],
            "nom": m["nom"],
            "color": m["color"],
            "confidence": metrics.confidence_tier(m["latin"]),
        }
        for m in core.MUSHROOMS
        if m["latin"] in served
    ]


def _valid_latins() -> set[str]:
    """Latins acceptés en entrée (préférences, filtres CSV) = espèces servies."""
    return set(core.fruiting_models())


WEB_DIR = settings.web_dir
OVERLAY_DIR = WEB_DIR / "overlays"

# PROD=1 active les protections de production (cookie HTTPS-only, /docs masqué).
PROD = os.environ.get("PROD") == "1"


# Secret de session : SESSION_SECRET (env) uniquement. Fail-closed en PROD (cf. config.py).
_SESSION_SECRET = resolve_session_secret(PROD)

app = FastAPI(
    title="Sporia",
    docs_url=None if PROD else "/docs",
    redoc_url=None if PROD else "/redoc",
    openapi_url=None if PROD else "/openapi.json",
)
app.add_middleware(
    SessionMiddleware,
    secret_key=_SESSION_SECRET,
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=PROD,  # cookie envoyé uniquement en HTTPS en prod
)


app.middleware("http")(security_headers)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
# Clé CARTO Basemaps (fonds de carte raster) : obligatoire depuis 2026-09 sinon filigrane
# « API key required » sur les tuiles. Clé publique par nature (visible côté navigateur)
# mais tenue hors du dépôt → .env. Absente = carte fonctionnelle, filigrane visible.
templates.env.globals["carto_key"] = os.environ.get("CARTO_API_KEY", "")


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


class Credentials(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(body: Credentials, request: Request):
    user = verify(body.username, body.password)
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
    account = accounts.get_by_email(user["username"]) if user else None
    return {
        "authenticated": bool(user),
        "name": user["name"] if user else None,
        "subscribed": billing.has_access(account),
        "role": (user or {}).get("role"),
        "price_label": os.environ.get("SPORIA_PRICE_LABEL", "15 €/an"),
    }


# ===== Inscription / mot de passe (auto-inscription) =====
class RegisterIn(BaseModel):
    email: str
    password: str
    name: str | None = None


class ForgotIn(BaseModel):
    email: str


class ResetIn(BaseModel):
    token: str
    password: str


def _valid_email(e: str) -> str:
    if not _EMAIL_RE.match(e or "") or len(e) > 120:
        raise HTTPException(status_code=400, detail="Email invalide.")
    return e.strip().lower()


@app.post("/api/register")
def register(body: RegisterIn, request: Request):
    email = _valid_email(body.email)
    if len(body.password or "") < 8:
        raise HTTPException(status_code=400, detail="Mot de passe trop court (min 8).")
    try:
        accounts.create_user(email, body.password, name=(body.name or "").strip() or None)
    except ValueError:
        raise HTTPException(
            status_code=409, detail="Un compte existe déjà pour cet email."
        ) from None
    tok = accounts.create_token(accounts.get_by_email(email)["id"], "verify", 7 * 24 * 3600)
    base = str(request.base_url).rstrip("/")
    send_email(
        email,
        "Bienvenue sur Sporia — vérifiez votre email",
        f"<p>Bienvenue ! Confirmez votre email : "
        f'<a href="{base}/api/verify-email?token={tok}">vérifier</a></p>',
    )
    user = verify(email, body.password)
    request.session["user"] = user
    return {"ok": True, "name": user["name"]}


@app.post("/api/password/forgot")
def password_forgot(body: ForgotIn, request: Request):
    u = accounts.get_by_email((body.email or "").strip().lower())
    if u:  # réponse toujours 200 neutre (anti-énumération)
        tok = accounts.create_token(u["id"], "reset", 3600)
        base = str(request.base_url).rstrip("/")
        send_email(
            u["email"],
            "Sporia — réinitialisation du mot de passe",
            f'<p>Réinitialisez : <a href="{base}/?reset={tok}">nouveau mot de passe</a> '
            f"(valide 1h)</p>",
        )
    return {"ok": True}


@app.post("/api/password/reset")
def password_reset(body: ResetIn):
    if len(body.password or "") < 8:
        raise HTTPException(status_code=400, detail="Mot de passe trop court (min 8).")
    uid = accounts.consume_token(body.token, "reset")
    if uid is None:
        raise HTTPException(status_code=400, detail="Lien invalide ou expiré.")
    accounts.set_password(uid, body.password)
    return {"ok": True}


@app.get("/api/verify-email")
def verify_email(token: str, request: Request):
    uid = accounts.consume_token(token, "verify")
    if uid is not None:
        accounts.set_verified(uid)
    return templates.TemplateResponse(request, "index.html", headers={"Cache-Control": "no-cache"})


# ===== Paiement / abonnement (Stripe) =====
@app.post("/api/billing/checkout")
def billing_checkout(user=Depends(require_user)):
    if not billing.stripe_enabled():
        raise HTTPException(status_code=503, detail="Paiement indisponible.")
    account = accounts.get_by_email(user["username"])
    return {"url": billing.create_checkout_session(account)}


@app.post("/api/billing/portal")
def billing_portal(user=Depends(require_user)):
    if not billing.stripe_enabled():
        raise HTTPException(status_code=503, detail="Paiement indisponible.")
    account = accounts.get_by_email(user["username"])
    try:
        url = billing.create_portal_session(account)
    except ValueError:
        raise HTTPException(status_code=400, detail="Aucun abonnement à gérer.") from None
    return {"url": url}


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        billing.process_event(payload, sig)
    except billing.WebhookError:
        raise HTTPException(status_code=400, detail="Webhook invalide.") from None
    return {"received": True}


@app.delete("/api/account")
def delete_account(request: Request, user=Depends(require_user)):
    """Effacement RGPD : résilie l'abonnement, purge les données, ferme la session."""
    account = accounts.get_by_email(user["username"])
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable.")
    billing.cancel_subscription(account)
    user_prefs.delete_user(account["email"])
    user_spots.delete_user(account["email"])
    accounts.delete_user(account["id"])
    request.session.clear()
    return {"ok": True}


# ===== API données (protégées) =====
@app.get("/api/dates")
def api_dates(user=Depends(require_subscription)):
    return {"dates": [d.strftime("%Y%m%d") for d in core.available_dates()]}


@app.get("/api/cities")
def api_cities(q: str = "", user=Depends(require_subscription)):
    return {"results": core.search_cities(q)}


@app.get("/api/outline")
def api_outline(user=Depends(require_subscription)):
    return core.france_outline_geojson() or {}


@app.get("/api/overlay")
def api_overlay(var: str, dates: str, user=Depends(require_subscription)):
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
def api_get_preferences(user=Depends(require_subscription)):
    catalog = _catalog()
    latins = {s["latin"] for s in catalog}
    sel = user_prefs.get_species(user["username"])
    # On restreint la sélection enregistrée au catalogue servi : une espèce retirée
    # du modèle (p.ex. morille déjà enregistrée par un compte) ne réapparaît pas.
    # Si rien de servi ne subsiste, on retombe sur « toutes les espèces servies ».
    kept = [s for s in sel if s in latins] if sel is not None else None
    return {"species": kept or [s["latin"] for s in catalog], "all": catalog, "saved": bool(kept)}


@app.post("/api/preferences")
def api_set_preferences(body: SpeciesPrefs, user=Depends(require_subscription)):
    valid_set = _valid_latins()
    valid = [s for s in body.species if s in valid_set]
    if not valid:
        raise HTTPException(status_code=400, detail="Sélection vide ou invalide.")
    user_prefs.set_species(user["username"], valid)
    return {"ok": True, "species": valid}


@app.get("/api/favorability")
def api_favorability(date: str, species: str | None = None, user=Depends(require_subscription)):
    # `species` explicite (CSV) sinon préférences enregistrées du compte (sinon toutes).
    sp = (
        _parse_species(species) if species is not None else user_prefs.get_species(user["username"])
    )
    res = core.render_favorability_overlay(_valid_date(date), species=sp)
    if res is None:
        raise HTTPException(status_code=404, detail="Favorabilité indisponible.")
    return res


@app.get("/api/soil")
def api_soil(user=Depends(require_subscription)):
    res = core.render_soil_overlay()
    if res is None:
        raise HTTPException(status_code=404, detail="Couche type de sol indisponible.")
    return res


@app.get("/api/soil-moisture")
def api_soil_moisture(date: str | None = None, user=Depends(require_subscription)):
    res = core.render_soil_moisture_overlay(_valid_date(date) if date else None)
    if res is None:
        raise HTTPException(status_code=404, detail="Couche humidité du sol indisponible.")
    return res


@app.get("/api/altitude")
def api_altitude(user=Depends(require_subscription)):
    res = core.render_altitude_overlay()
    if res is None:
        raise HTTPException(status_code=404, detail="Couche altitude indisponible.")
    return res


@app.get("/api/aspect")
def api_aspect(user=Depends(require_subscription)):
    res = core.render_aspect_overlay()
    if res is None:
        raise HTTPException(status_code=404, detail="Couche exposition indisponible.")
    return res


@app.get("/api/radar")
def api_radar(
    date: str | None = None, species: str | None = None, user=Depends(require_subscription)
):
    """« Radar à champignons » : carte habitat×moment agrégée sur la sélection du compte
    (ou `species` CSV), restreinte aux espèces ayant un modèle servi."""
    sel = (
        _parse_species(species) if species is not None else user_prefs.get_species(user["username"])
    )
    served = set(core.fruiting_models())
    sel = [s for s in (sel or [m["latin"] for m in core.MUSHROOMS]) if s in served]
    res = core.render_radar_overlay(sel, _valid_date(date) if date else None)
    if res is None:
        raise HTTPException(
            status_code=404, detail="Radar indisponible (aucune espèce modélisée sélectionnée)."
        )
    return res


def _radar_selection(species: str | None, username: str) -> list[str]:
    sel = _parse_species(species) if species is not None else user_prefs.get_species(username)
    served = set(core.fruiting_models())
    return [s for s in (sel or [m["latin"] for m in core.MUSHROOMS]) if s in served]


@app.get("/api/radar/meta")
def api_radar_meta(species: str | None = None, user=Depends(require_subscription)):
    """Espèces (noms FR) réellement affichées sur le radar (en saison) — pour la légende."""
    return {"species": core.radar_tile_species(_radar_selection(species, user["username"]))}


@app.get("/api/radar/tiles/{z}/{x}/{y}.png")
def api_radar_tile(
    z: int,
    x: int,
    y: int,
    sp: str | None = None,
    d: str | None = None,
    user=Depends(require_subscription),
):
    """Tuile PNG du « Radar à champignons » (valeur lissée × contour forêt exact). `d`
    ne sert qu'au cache navigateur (invalidation quotidienne)."""
    png = core.radar_tile_png(z, x, y, _radar_selection(sp, user["username"]))
    return Response(
        content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"}
    )


@app.get("/api/fruiting-models")
def api_fruiting_models(user=Depends(require_subscription)):
    """Espèces disposant d'un modèle « pousse en ce moment » (point #4)."""
    latins = core.fruiting_models()
    by_latin = {m["latin"]: m for m in core.MUSHROOMS}
    return {"species": [{"latin": x, "nom": by_latin.get(x, {}).get("nom", x)} for x in latins]}


@app.get("/api/fruiting")
def api_fruiting(species: str, date: str | None = None, user=Depends(require_subscription)):
    """Carte de probabilité de fructification du jour pour une espèce (modèle
    météo-dépendant appliqué aux ~21 derniers jours via Open-Meteo)."""
    if species not in core.fruiting_models():
        raise HTTPException(status_code=404, detail="Aucun modèle de pousse pour cette espèce.")
    res = core.render_fruiting_overlay(species, _valid_date(date) if date else None)
    if res is None:
        raise HTTPException(
            status_code=503, detail="Indice de pousse indisponible (météo récente)."
        )
    return res


@app.get("/api/point")
def api_point(lat: float, lon: float, date: str, user=Depends(require_subscription)):
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="Coordonnées invalides.")
    sel = user_prefs.get_species(user["username"])
    return core.point_report(lat, lon, _valid_date(date), selected=sel)


@app.get("/api/forest")
def api_forest(lat: float, lon: float, user=Depends(require_subscription)):
    """Essence précise au point (BD Forêt WMS) — appelée en différé par l'UI, hors
    du chemin critique du clic (qui n'utilise que la famille bakée). Best-effort."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="Coordonnées invalides.")
    return mmap.forest_at_point(round(lat, 4), round(lon, 4)) or {}


# ===== Spots enregistrés (« mes coins ») + alerte « propice » =====
class SpotIn(BaseModel):
    lat: float
    lon: float
    name: str | None = None


class SpotPatch(BaseModel):
    name: str


@app.get("/api/spots")
def api_list_spots(user=Depends(require_subscription)):
    """Spots du compte enrichis du statut « propice » courant (échantillonné sur
    le radar habitat × pousse du jour, selon la sélection d'espèces du compte)."""
    spots = user_spots.list_spots(user["username"])
    sel = user_prefs.get_species(user["username"])
    return {"spots": core.spots_status(spots, selected=sel)}


@app.post("/api/spots")
def api_add_spot(body: SpotIn, user=Depends(require_subscription)):
    if not (-90 <= body.lat <= 90 and -180 <= body.lon <= 180):
        raise HTTPException(status_code=400, detail="Coordonnées invalides.")
    spot = user_spots.add_spot(user["username"], body.lat, body.lon, body.name or "")
    return {"ok": True, "spot": spot}


@app.patch("/api/spots/{spot_id}")
def api_rename_spot(spot_id: str, body: SpotPatch, user=Depends(require_subscription)):
    if not (body.name or "").strip():
        raise HTTPException(status_code=400, detail="Nom vide.")
    if not user_spots.rename_spot(user["username"], spot_id, body.name):
        raise HTTPException(status_code=404, detail="Spot introuvable.")
    return {"ok": True}


@app.delete("/api/spots/{spot_id}")
def api_delete_spot(spot_id: str, user=Depends(require_subscription)):
    if not user_spots.delete_spot(user["username"], spot_id):
        raise HTTPException(status_code=404, detail="Spot introuvable.")
    return {"ok": True}


# ===== Demande d'accès / contact (site sur invitation) =====
class AccessRequestIn(BaseModel):
    name: str
    email: str
    message: str
    hp: str | None = None  # honeypot anti-bot (doit rester vide)


@app.post("/api/access-request")
def api_access_request(body: AccessRequestIn):
    """Demande d'accès publique (non authentifiée). Honeypot + validation + cap.
    Rate-limitée par nginx (zone /api/)."""
    if (body.hp or "").strip():  # bot : on fait comme si OK, sans rien stocker
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
    _notify_admin_access_request(name, email, message)
    return {"ok": True}


def _notify_admin_access_request(name: str, email: str, message: str) -> None:
    """Prévient l'admin par email d'une nouvelle demande d'accès (best-effort).

    Destinataire = ADMIN_EMAIL (env). Absent (ou pas de BREVO_API_KEY) → no-op.
    Champs échappés (contenu utilisateur) pour éviter toute injection HTML."""
    admin_to = os.environ.get("ADMIN_EMAIL", "").strip()
    if not admin_to:
        return
    body_html = (
        "<p><strong>Nouvelle demande d'accès Sporia :</strong></p>"
        f"<p><b>Nom :</b> {html.escape(name)}<br>"
        f"<b>Email :</b> {html.escape(email)}</p>"
        f"<p><b>Message :</b><br>{html.escape(message).replace(chr(10), '<br>')}</p>"
    )
    send_email(admin_to, "Sporia — nouvelle demande d'accès", body_html)


@app.get("/api/access-requests")
def api_list_access_requests(user=Depends(require_admin)):
    """Liste des demandes d'accès — RÉSERVÉ ADMIN (contient des emails).
    Nécessite `role: admin` sur le compte dans config.yaml."""
    return {"requests": access_requests.list_requests()}


class CreateFromRequestIn(BaseModel):
    request_id: str


@app.post("/api/admin/accounts/from-request")
def api_create_account_from_request(
    body: CreateFromRequestIn, request: Request, user=Depends(require_admin)
):
    """Crée un compte à partir d'une demande d'accès, puis retire la demande — RÉSERVÉ ADMIN.

    Le compte a un mot de passe aléatoire inutilisable ; un lien d'invitation (jeton reset,
    7 j) permet à la personne de définir le sien. Le lien est envoyé par email (best-effort)
    ET renvoyé pour affichage/copie (utile si l'email n'est pas configuré)."""
    req = access_requests.get_request(body.request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Demande introuvable.")
    email = _valid_email(req["email"])
    try:
        acc = accounts.create_user(
            email, secrets.token_urlsafe(24), name=(req.get("name") or "").strip() or None
        )
    except ValueError:
        raise HTTPException(
            status_code=409, detail="Un compte existe déjà pour cet email."
        ) from None
    # Une demande acceptée = un bêta-testeur : accès offert, sans passage par le paywall.
    accounts.set_subscription(acc["id"], "beta")
    token = accounts.create_token(acc["id"], "reset", 7 * 24 * 3600)
    invite_url = f"{str(request.base_url).rstrip('/')}/?reset={token}"
    send_email(
        email,
        "Votre accès à Sporia",
        f"<p>Un compte Sporia a été créé pour vous. Définissez votre mot de passe : "
        f'<a href="{invite_url}">choisir mon mot de passe</a> (lien valide 7 jours).</p>',
    )
    access_requests.remove_request(body.request_id)
    return {"ok": True, "email": email, "invite_url": invite_url}


@app.delete("/api/access-requests/{req_id}")
def api_delete_access_request(req_id: str, user=Depends(require_admin)):
    """Refuse/retire une demande d'accès sans créer de compte — RÉSERVÉ ADMIN."""
    if not access_requests.remove_request(req_id):
        raise HTTPException(status_code=404, detail="Demande introuvable.")
    return {"ok": True}


class AccountAccessIn(BaseModel):
    email: str
    status: str


@app.get("/api/admin/accounts")
def api_admin_accounts(user=Depends(require_admin)):
    """Liste des comptes pour l'écran d'administration — RÉSERVÉ ADMIN."""
    items, truncated = accounts.list_accounts()
    return {"accounts": items, "truncated": truncated}


@app.post("/api/admin/accounts/access")
def api_admin_set_access(body: AccountAccessIn, user=Depends(require_admin)):
    """Accorde ou retire l'accès bêta d'un compte — RÉSERVÉ ADMIN.

    Refuse les comptes admin (le rôle donne déjà l'accès) et les comptes à
    abonnement Stripe actif (leur statut appartient à Stripe, pas à cet écran)."""
    status = (body.status or "").strip()
    if status not in ("beta", "none"):
        raise HTTPException(status_code=400, detail="Statut invalide (beta ou none).")
    account = accounts.get_by_email(_valid_email(body.email))
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable.")
    if account.get("role") == "admin":
        raise HTTPException(status_code=409, detail="Un compte admin a déjà l'accès complet.")
    if account.get("subscription_status") == "active":
        raise HTTPException(
            status_code=409, detail="Abonnement Stripe actif : statut géré par Stripe."
        )
    accounts.set_subscription(account["id"], status)
    return {"ok": True, "email": account["email"], "status": status}


# ===== Statique =====
OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/overlays", StaticFiles(directory=str(OVERLAY_DIR)), name="overlays")
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


# ===== PWA (coquille seule) =====
@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Servi à la racine → scope du SW = tout le site. no-cache pour maj immédiate.
    return FileResponse(
        str(WEB_DIR / "sw.js"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(
        str(WEB_DIR / "manifest.webmanifest"), media_type="application/manifest+json"
    )


@app.get("/")
def index(request: Request):
    # no-cache sur le document HTML → la référence versionnée de app.js est toujours fraîche
    return templates.TemplateResponse(
        request,
        "index.html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )
