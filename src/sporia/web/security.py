"""En-têtes de sécurité HTTP + Content-Security-Policy (extrait de server.py)."""

from __future__ import annotations

from fastapi import Request

# CSP : autorise uniquement les CDN réellement utilisés par l'UI (Tailwind, Leaflet/unpkg,
# Google Fonts) + les tuiles carto/IGN en image. 'unsafe-inline' nécessaire (config Tailwind
# + styles inline dans index.html) ; les données utilisateur rendues en HTML sont échappées.
CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://unpkg.com https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https:; "
    "connect-src 'self'; "
    "frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
)


async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Content-Security-Policy", CSP)
    return resp
