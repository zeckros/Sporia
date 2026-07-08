"""En-têtes de sécurité HTTP + Content-Security-Policy (extrait de server.py)."""

from __future__ import annotations

from fastapi import Request

# CSP : tout en self après self-hosting (Tailwind CLI + Leaflet + Inter vendorés).
# 'unsafe-inline' conservé pour script + style tant que subsistent des scripts/handlers
# inline et les styles inline injectés par Leaflet (el.style). Le retrait de 'unsafe-inline'
# sur script-src est prévu au Plan 2 (modules ES : plus d'inline). Données rendues échappées.
CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
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
    resp.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
    return resp
